import datetime
import json
import logging
import os
import sys
from calendar import monthrange, week
from datetime import datetime as dt
from datetime import timedelta
from random import choice
import requests
from string import ascii_uppercase

import arcgis
import arcpy
import arcpy.da

from datetime import date
import datetime
import pandas
"""
Input 
   1. Input Orders Table
   2. Input Depot Table
   3. Build Orders, Depots, and Routes classes for loading into VRP
   4. Build VRP
VRP Solve
   5. Solve VRP
   6. Output on Success or Failure

"""
######### Settings block
network_location = "local" #Options are "local" or "portal"
nds = r"C:\SMP_NA_AGOL_July2023\northamerica.geodatabase\Routing\Routing_ND"
nd_layer_name = "NorthAmerica"
input_orders_txt = r"C:\Projects\NetworkAnalystDemos\PythonVRP\Orders.csv"
input_depot_txt = r"C:\Projects\NetworkAnalystDemos\PythonVRP\Depot.csv"
explicit_scratch_path = r"C:\Temp"
solve_folder =  r"C:\Temp" #folder to dump artifacts
input_class_templates_fgdb = r"C:\Projects\NetworkAnalystDemos\PythonVRP\Templates.gdb"
start_date = datetime.datetime(2023, 1, 31) #is a date we can set if we don't find a date in the time windows and route start times
mtt = 480 #max total time for routes in minutes
route_count = 10 #number of routes to give the solver
log_level = 10 # NOTSET=0, DEBUG=10, INFO=20, WARN=30, ERROR=40, and CRITICAL=50.
travelmode_desc = "Driving Time"
vrp_overrides = '{"VrpEngine":"MediumDensity","VrpFastOdTargetDestCount": 1250,"VrpFastOdMinOrderCount": 3000}'
#vrp_overrides = ""
######### End Settings block

if network_location == "local":
   if arcpy.CheckExtension("Network") == "Available":
      arcpy.CheckOutExtension("Network")
   else:
       print("Network extension not available")


#Get references to the empty templates 
depot_template_lyr = arcpy.MakeFeatureLayer_management(input_class_templates_fgdb + "\DepotTemplate", "depot_template_lyr")
orders_template_lyr = arcpy.MakeFeatureLayer_management(input_class_templates_fgdb + "\OrdersTemplate", "orders_template_lyr")
routes_template_lyr = arcpy.MakeFeatureLayer_management(input_class_templates_fgdb + "\RoutesTemplate", "routes_template_lyr")


#Create File Geodatabase workspace
arcpy.env.overwriteOutput = True
explicit_scratch_ws = arcpy.CreateFileGDB_management(explicit_scratch_path, "scratch.gdb")
arcpy.env.workspace = os.path.join(explicit_scratch_path, "scratch.gdb")

#Create the empty feature classes for orders, routes, and depots from templates
vrp_input_depot = arcpy.CreateFeatureclass_management(explicit_scratch_ws, "InputDepot", "POINT", depot_template_lyr, "DISABLED", "DISABLED", arcpy.Describe(depot_template_lyr).spatialReference)
vrp_input_orders = arcpy.CreateFeatureclass_management(explicit_scratch_ws, "InputOrders", "POINT", orders_template_lyr, "DISABLED", "DISABLED", arcpy.Describe(orders_template_lyr).spatialReference)
vrp_input_routes = arcpy.CreateFeatureclass_management(explicit_scratch_ws, "InputRoutes", "POLYLINE", routes_template_lyr, "DISABLED", "DISABLED", arcpy.Describe(routes_template_lyr).spatialReference)

orders_from_text = os.path.join(arcpy.env.workspace, "text_orders")
depot_from_text = os.path.join(arcpy.env.workspace, "text_depot")
x_coords = "POINT_X"
y_coords = "POINT_Y"

#Make the XY event layer for orders and depot
arcpy.management.XYTableToPoint(input_orders_txt, orders_from_text,x_coords, y_coords, "", arcpy.SpatialReference(4326))
arcpy.management.XYTableToPoint(input_depot_txt, depot_from_text,x_coords, y_coords, "", arcpy.SpatialReference(4326))

#insert records from the event layers into empty Orders and Depot tables
vrp_depot_fields = ['Name', 'SHAPE@']
vrp_depot_insert_cur = arcpy.da.InsertCursor(vrp_input_depot, vrp_depot_fields)

text_depot_fields = ['Station','SHAPE@']
with arcpy.da.SearchCursor(depot_from_text, text_depot_fields) as depot_read_cursor:
    for depot in depot_read_cursor:
        depot_name = depot[0]
        vrp_depot_insert_cur.insertRow([depot[0], depot[1]])

del vrp_depot_insert_cur

vrp_orders_fields = ['Name', 'SHAPE@','ServiceTime','TimeWindowStart','TimeWindowEnd']
vrp_orders_insert_cur = arcpy.da.InsertCursor(vrp_input_orders, vrp_orders_fields)

text_orders_fields = ['Name','SHAPE@','AtStop','TWStart','TWEnd']
with arcpy.da.SearchCursor(orders_from_text, text_orders_fields) as orders_read_cursor:
    for order in orders_read_cursor:
        time_window_earliest = order[3] #I cheated here just to get some operating times for routes - you'll want to do better
        time_window_latest = order[4]
        vrp_orders_insert_cur.insertRow([order[0], order[1], order[2], order[3], order[4]])

del vrp_orders_insert_cur

vrp_routes_fields = ['Name', 'StartDepotName','EndDepotName','EarliestStartTime','LatestStartTime','ArriveDepartDelay','FixedCost','CostPerUnitTime','MaxOrderCount','MaxTotalTime']
input_routes_insert_cur = arcpy.da.InsertCursor(vrp_input_routes, vrp_routes_fields)

for routes in range(route_count):
    input_routes_insert_cur.insertRow(["Route_" + str(routes), depot_name, depot_name, time_window_earliest, time_window_latest, 0.1, 100, 1.0, 200, mtt])

del input_routes_insert_cur

#Instantiate a Vehicle Routing Problem analysis object
arcpy.nax.MakeNetworkDatasetLayer(nds, nd_layer_name)
vrp = arcpy.nax.VehicleRoutingProblem(nd_layer_name)

#Get the desired travel mode for the analysis
nd_travel_modes = arcpy.nax.GetTravelModes(nd_layer_name)
travel_mode = nd_travel_modes[travelmode_desc]

#Set properties
vrp.travelMode = travel_mode
vrp.distanceUnits = arcpy.nax.DistanceUnits.Miles
vrp.timeUnits = arcpy.nax.TimeUnits.Minutes
vrp.routeShapeType = arcpy.nax.RouteShapeType.TrueShape
vrp.returnDirections = False
vrp.returnStopShapes = True
vrp.allowSaveLayerFile = True
vrp.overrides = vrp_overrides
    
#We need the solve to fail if any orders are not located in network edges. user must address this condition
vrp.ignoreInvalidLocations = False

# Load inputs
vrp.load(arcpy.nax.VehicleRoutingProblemInputDataType.Orders, str(explicit_scratch_ws) + "\InputOrders")
vrp.load(arcpy.nax.VehicleRoutingProblemInputDataType.Depots, str(explicit_scratch_ws) + "\InputDepot")
vrp.load(arcpy.nax.VehicleRoutingProblemInputDataType.Routes, str(explicit_scratch_ws) + "\InputRoutes")

# Solve the analysis
result = vrp.solve()

# Export the results to feature classes
if result.solveSucceeded:
    print("Solve Succeeded")
    result.export(arcpy.nax.VehicleRoutingProblemOutputDataType.Stops, os.path.join(explicit_scratch_path, "scratch.gdb", "output_orders"))
    result.export(arcpy.nax.VehicleRoutingProblemOutputDataType.Routes, os.path.join(explicit_scratch_path, "scratch.gdb", "output_routes"))
    out_layer = explicit_scratch_path + "/PythonVRP_Example.lpkx"
    result.saveAsLayerFile(out_layer)
else:
    print("Solve Failed")
    out_layer = explicit_scratch_path + "/PythonVRP_Example_failed.lpkx"
    result.saveAsLayerFile(out_layer)

