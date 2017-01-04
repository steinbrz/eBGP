import signal
import sys
import socket
import threading
import math
from struct import *
from select import *
import time
import copy
import time


__LOCAL__ = 0
__CUSTOMER__ = 1
__PEER__ = 2
__PROVIDER__ = 3



class prefix_object(object):

    def __init__(self, prefix):

        self.prefix = prefix
        self.ip, length = prefix.split("/")

        self.len = int(length)
        self.mask = 0
        subnet_range = 32 - self.len
        for i in range(subnet_range, 33):
            self.mask = self.mask | (1 << i)

        first, second, third, fourth = self.ip.split(".")
        self.binary = (int(first) << 24) | (int(second) << 16) | (int(third) << 8) | int(fourth)
        self.prefix = prefix

    def compare_ip(self, ip):

        first, second, third, fourth = ip.split(".")
        binary = (int(first) << 24) | (int(second) << 16) | (int(third) << 8) | int(fourth)

        check1 = self.mask & self.binary
        check2 = self.mask & binary

        if check1 ^ check2 == 0:
            return True
        else:
            return False

    def __lt__(self, other):

        if self.binary != other.binary:
            return self.binary < other.binary
        else:
            return self.len < other.len

    def __eq__(self, other):

        if self.binary == other.binary and self.len == other.len:
            return 1 == 1
        else:
            return 1 == 2


class update(object):

    def __init__(self):

        self.type = None
        self.route = None


    ######################################################################
    def encode(self, t, route):
        self.route = route
        self.type = t
        if self.route.len > 0:
            msg = self.type + " "
            msg += self.route.encode_route()
            msg += "\n"
            self.packet = msg.encode()

    ######################################################################


    def decode(self, msg):
        self.route = route()
        self.type, r = msg.split(" ", 1)
        self.route.decode_updated_route(r)

    ######################################################################

class routing_table(object):

    def __init__(self):
        self.connection_type = {}
        self.neighbor_ids = {}
        self.routes = {}
        self.new_routes = []
        #self.ordered_prefix_list = []

    ######################################################################

    def add_route(self, route, t,  address):

        # if the prefix doesn't already exist, make a blank list and add the route
        time_added = time.time()
        route.set_time(time_added)
        route.set_connection_type(t)

        if route.prefix not in self.routes:
            new_prefix = prefix_object(route.prefix)
            #self.ordered_prefix_list.append(new_prefix)
            #self.ordered_prefix_list.sort()
            self.routes[route.prefix] = []
            self.routes[route.prefix].append(route)
            self.routes[route.prefix].sort()

        #if it does, append to current list of routes to prefix
        else:
            #print("In else statement")
            #print("Route is {} {}".format(route.prefix, route.stops))
            #for r in self.routes[route.prefix]:
                #print("Route in list: {} {}\n".format(r.prefix, r.stops))

            if route not in self.routes[route.prefix]:
                #print(" route hasn't been added")

                self.routes[route.prefix].append(route)
                self.routes[route.prefix].sort()


    ######################################################################
    def best_prefix_route(self, prefix):

        if prefix in self.routes:
            r_list = self.routes[prefix]
            best = r_list[0]
            return best
        else:
            return None
    ######################################################################


    def withdraw_route(self, route):
        for key in self.routes:
            if key == route.prefix:
                for r in self.routes[key]:
                    if r.stops == route.stops:
                        self.routes[key].remove(r)
                        # no more routes to prefix, eliminate entry
                        if len(self.routes[key]) == 0:
                            del self.routes[key]
                            r_prefix = prefix_object(copy.deepcopy(route.prefix))

                            # since no route to prefix, remove from ordered list
                            #for rp in self.ordered_prefix_list:
                                #if rp == r_prefix:
                                    #self.ordered_prefix_list.remove(rp)
                                    #self.ordered_prefix_list.sort()
                                    #break
                        else:
                            self.routes[key].sort()

                        return

    ######################################################################

    def remove_routes_from_neighbor(self, neighbor):

        return_routes = []
        #print(self.routes)


        for key in self.routes:

            for r in self.routes[key]:
                if r.origin == neighbor:
                    temp = copy.deepcopy(r)
                    return_routes.append(temp)
                    self.routes[key].remove(r)
                    self.routes[key].sort()

        prefixes_to_delete = []
        # go through route table and find prefixes we no longer have a path too
        for key in self.routes:
            if len(self.routes[key]) == 0:
                prefixes_to_delete.append(key)
                r_prefix = prefix_object(key)
                #for rp in self.ordered_prefix_list:
                    #if rp == r_prefix:
                        #self.ordered_prefix_list.remove(rp)
                        #self.ordered_prefix_list.sort()
                        #break
        # delete the prefixes we found
        for p in prefixes_to_delete:
            del self.routes[p]

        return return_routes


    ######################################################################




##################################################################################################################
##################################################################################################################

class route(object):

    def __init__(self, prefix=None, t=None):
        self.stops = []
        self.origin = None
        self.len = 0
        self.prefix = prefix
        self.connection_type = t
        self.receive_time = None

    ######################################################################

    def set_time(self, receive_time):
        self.receive_time = receive_time

    ######################################################################


    def set_connection_type(self, connection_type):
        self.connection_type = connection_type
    ######################################################################

    def to_string(self):
        ret_string = ''
        for s in self.stops:
            ret_string += "{} ".format(s)
        return ret_string

    ######################################################################


    def add_origin(self, stop):
        self.stops.insert(0, stop)
        self.origin = self.stops[0]
        self.len = len(self.stops)
    ######################################################################


    def encode_route(self):
        msg = self.prefix
        for s in self.stops:
            msg += " {}".format(s)

        return msg
    ######################################################################
    def route_through_id(self, local_id):
        if local_id == None:
            return False

        for i in self.stops:
            if i == local_id:
                return True

        return False
    ######################################################################

    def decode_updated_route(self, route):
        prefix, temp = route.split(" ", 1)
        stops = temp.split(" ")
        self.prefix = prefix
        for s in stops:
            self.stops.append(s)
        self.origin = self.stops[0]
        self.len = len(self.stops)
    ######################################################################

    def __lt__(self, other):

        if self.connection_type != other.connection_type:
            return self.connection_type < other.connection_type
        elif self.len != other.len:
            return self.len < other.len
        else:
            return self.receive_time < other.receive_time

    ######################################################################
    def __eq__(self, other):
        if other == None:
            return 1 == 2
        elif self.origin == other.origin and self.connection_type == other.connection_type and self.len == other.len and self.receive_time == other.receive_time:
            return 1 == 1
        else:
            return 1 == 2
