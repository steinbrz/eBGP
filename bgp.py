import signal
import sys
import socket
import threading
import math
from struct import *
from select import *
from data_handler import *
import time
import copy
from queue import *



__CUSTOMER__ = 1
__PEER__ = 2
__PROVIDER__ = 3
__LOCAL__ = 0
__CONNECTION_OPEN__ = 1
__CONNECTION_CLOSED__ = 2


class BGP(object):


    #######################################################################
    def __init__(self, number, port):

        self.port = port
        self.id = number
        self.state = __CONNECTION_OPEN__
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', int(port)))
        self.server_address = self.socket.getsockname()
        self.routing_table = routing_table()
        #self.routing_table.add_connection_type(self.server_address, __LOCAL__)
        self.socket.listen(10)
        self.socket.setblocking(False)
        self.threads = []
        self.connections = {}
        self.socket_list = []
        self.read_buffer = {}
        self.neighbor_ids = {}
        self.connection_type = {}
        self.peer_list = []
        self.f = open("file{}.txt".format(number), 'w')

        self.address = self.socket.getsockname()
        self.connection_type[self.address] = __LOCAL__
        self.neighbor_ids[self.address] = self.id


        self.lock = threading.Lock()

        #Conneciton thread handles incoming connecitons and update thread handles update communication
        self.connection_thread = threading.Thread(target = self.connection_handler)
        self.update_thread = threading.Thread(target = self.update_handler)
        self.threads.append(self.connection_thread)
        self.threads.append(self.update_thread)
        self.connection_thread.start()
        self.update_thread.start()


    ######################################################################

    def connection_handler(self):

        accept_socket = [self.socket]
        while self.state == __CONNECTION_OPEN__:

            readable, writeable, exeptions = select(accept_socket, accept_socket, accept_socket, 0)
            if self.socket in readable:
                new_socket, address = self.socket.accept()
                #print("Received connection from {}\n".format(address))

                # process connection and receive conneciton type information
                self.lock.acquire()

                # received and decode message
                new_socket.setblocking(True)
                msg = new_socket.recv(50)


                # receive initialization message and log as_number of neighbor and its type
                decoded_msg = msg.decode()
                end = decoded_msg.find("\n")
                temp = decoded_msg[:end]
                as_number, t = temp.split(" ")
                #print("CH Adding neighbor: {}".format(as_number))


                return_msg = self.id + '\n'
                new_socket.send(return_msg.encode())

                new_socket.setblocking(False)

                # type sent is what we are to them, so they are the opposite or peer to us
                if t == "peer":
                    their_type = __PEER__
                elif t == "provider":
                    their_type = __CUSTOMER__
                else:
                    their_type = __PROVIDER__

                # log information
                self.neighbor_ids[address] = as_number
                self.connection_type[address] = their_type
                self.socket_list.append(new_socket)
                self.connections[address] = new_socket
                self.read_buffer[address] = ""
                self.peer_list.append(address)

                # send best routes to new connection
                self.send_update_on_connect(address)


                self.lock.release()

                # need logic to export best routes to new connection


    ######################################################################

    def send_update_on_connect(self, address):
        s = self.connections[address]


        #print("Update on connect")
        for key in self.routing_table.routes:
            route_list = self.routing_table.routes[key]
            new_route = route_list[0]
            origin = new_route.origin
            if origin == None:
                origin_type = __LOCAL__
            else:
                origin_address = self.get_address_from_id(origin)
                origin_type = self.connection_type[origin_address]

            connection_type = self.connection_type[address]

            #print(" Connected Addres: {}".format(address))
            #print("Route is {}, type is {}".format(new_route.stops, origin_type))
            #print("Connection type is {}".format(connection_type))
            forward_route = copy.deepcopy(new_route)
            forward_route.add_origin(self.id)
            forward_update = update()
            forward_update.encode("A", forward_route)



            #export rules
            if origin_type == __LOCAL__:
                #print("sending")
                s.send(forward_update.packet)
            elif origin_type == __PROVIDER__ or origin_type == __PEER__:
                if connection_type == __CUSTOMER__:
                    #print("sending")
                    s.send(forward_update.packet)
                else:
                    continue
            else:
                #print("sending")
                s.send(forward_update.packet)



    ######################################################################




    def update_handler(self):

        while self.state == __CONNECTION_OPEN__:


            readable, writeable, exceptions = select(self.socket_list, [], self.socket_list, 0)


            for r in readable:
                # receive update
                self.lock.acquire()
                msg = r.recv(1000)
                address = self.get_address(r)

                # if we get 0 bytes, other socket was closed
                if len(msg) == 0:
                    as_number = self.neighbor_ids[address]
                    withdraw_list = self.routing_table.remove_routes_from_neighbor(as_number)

                    # send withdraw statements for any routes that went through this neighbor

                    if len(withdraw_list) > 0:

                        for w in withdraw_list:
                            self.send_updates("W", w, address)
                            new_best_route = self.routing_table.best_prefix_route(w.prefix)

                            if new_best_route == None:
                                continue
                            else:
                                origin = new_best_route.origin
                                rec_address = self.get_address_from_id(origin)
                                self.send_updates("A", new_best_route, rec_address)


                    self.socket_list.remove(r)
                    r.close()
                    del self.neighbor_ids[address]
                    del self.read_buffer[address]
                    self.peer_list.remove(address)
                    del self.connections[address]
                    self.lock.release()
                    continue

                decoded_msg = msg.decode()
                self.read_buffer[address] += decoded_msg

                while True:

                    end_of_update = self.read_buffer[address].find("\n")
                    if end_of_update == -1:
                        break


                    #process update
                    temp = self.read_buffer[address]
                    new_update = update()
                    new_update.decode(temp[:end_of_update])
                    self.read_buffer[address] = self.read_buffer[address][end_of_update + 1:]
                    new_route = new_update.route
                    #print("Received route: {} {}, update type {}".format(new_route.prefix, new_route.stops, new_update.type))

                    #print("Through ID {}".format(new_route.route_through_id(self.id)))
                    # if new route doesn't go through us already
                    if not new_route.route_through_id(self.id):
                        # if it is a withdraw, remove from route from routing table
                        if new_update.type == "W":
                            #print("Received Withdraw")
                            original_best_route = self.routing_table.best_prefix_route(new_route.prefix)
                            self.routing_table.withdraw_route(new_update.route)
                            new_best_route = self.routing_table.best_prefix_route(new_route.prefix)

                            #check if we need to advertise a new best route
                            #if we don't have the prefix route, pass on to others
                            self.send_updates("W", new_route, address)

                            #if new_best_route == None:
                                #self.send_updates("W", new_route, address)
                                #print("Withdraw, no more routes to prefix")
                                #print("New best route {} {}".format(new_route.prefix, new_route.stops))
                            #elif new_best_route == original_best_route:
                                #print("Best Route is still the same")
                                #continue
                            if new_best_route == original_best_route:
                                continue
                            elif new_best_route != None:
                                #print("Withdraw, new best route to prefix")
                                #print("Old best route {} {}".format(original_best_route.prefix, original_best_route.stops))
                                #print("New best route {} {}".format(new_best_route.prefix, new_best_route.stops))
                                #self.send_updates("W", original_best_route, address)
                                origin = new_best_route.origin
                                origin_address = self.get_address_from_id(origin)
                                self.send_updates("A", new_best_route, origin_address)

                        #else add to routing table
                        else:
                            #print("Received Advertisement")
                            original_best_route = self.routing_table.best_prefix_route(new_route.prefix)
                            new_route_type = self.connection_type[address]
                            #print("Adding route from update handler")
                            self.routing_table.add_route(new_update.route, new_route_type, address)
                            new_best_route = self.routing_table.best_prefix_route(new_route.prefix)

                            # if we received a new route that is better than our first best
                            # if we don't already have a route to that prefix, advertise new route
                            if original_best_route == None:
                                #print("Advertise, new route is only route and best")
                                #print("New best route {} {}".format(new_best_route.prefix, new_best_route.stops))
                                self.send_updates("A", new_best_route, address)
                            elif new_best_route == original_best_route:
                                #print("Best route is still the same")
                                continue
                            else:
                                #print("Advertise, new route is best route to prefix, withdraw old")
                                #print("Old best route {} {}".format(original_best_route.prefix, original_best_route.stops))
                                #print("New best route {} {}".format(new_best_route.prefix, new_best_route.stops))
                                origin = original_best_route.origin
                                origin_address = self.get_address_from_id(origin)
                                self.send_updates("W", original_best_route, origin_address)
                                self.send_updates("A", new_best_route, address)



                self.lock.release()

    ######################################################################

    def get_address(self, socket):

        for key in self.connections:
            if self.connections[key] == socket:
                return key
        return None

    ######################################################################

    def get_address_from_id(self, id_num):
        for key in self.neighbor_ids:
            if self.neighbor_ids[key] == id_num:
                return key


    ######################################################################

    def send_updates(self, t, new_route, rec_address):

        forward_route = copy.deepcopy(new_route)
        forward_route.add_origin(self.id)
        forward_update = update()
        forward_update.encode(t, forward_route)

        for s in self.socket_list:

            if self.forwarding_filter( s, forward_route, rec_address):
                #print("Sending route {} {}".format(forward_route.prefix, forward_route.stops))
                s.send(forward_update.packet)



    ######################################################################

    def forwarding_filter(self, s, route, rec_address):

        rec_type = self.connection_type[rec_address]
        forward_address = self.get_address(s)
        as_number = self.neighbor_ids[forward_address]
        forward_type = self.connection_type[forward_address]

        #print(" Forward_address {}, type {}".format(forward_address, forward_type))
        #print(" Rec_address {}, type {}".format(rec_address, forward_address))

        if rec_address == forward_address:
            return False
        elif route.route_through_id(as_number):
            return False
        elif rec_type == __PROVIDER__ or rec_type == __PEER__:

            if forward_type == __CUSTOMER__:
                return True
            else:
                return False
        else:
            return True


    ######################################################################

    def connect(self, t , host, port):


        self.lock.acquire()
        address = (host, int(port))
        new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        new_socket.connect(address)

        #send what they are to us
        msg = self.id + " " + t + '\n'
        new_socket.send(msg.encode())
        new_socket.setblocking(True)

        #get acknowledge with neighbor's id number
        ack = new_socket.recv(15)
        decoded_ack = ack.decode()
        eou = decoded_ack.find("\n")
        as_number = decoded_ack[:eou]
        #self.routing_table.add_neighbor_id(address, as_number)
        new_socket.setblocking(False)



        #specified connection type is what they are to us
        if t == "peer":
            their_type = __PEER__
        elif t == "customer":
            their_type = __CUSTOMER__
        else:
            their_type = __PROVIDER__

        #connected_address = new_socket.getpeername()
        self.connection_type[address] = their_type
        self.connections[address] = new_socket
        self.socket_list.append(new_socket)
        self.neighbor_ids[address] = as_number

        self.send_update_on_connect(address)
        self.read_buffer[address] = ""
        self.peer_list.append(address)

        self.lock.release()




    ######################################################################
    def disconnect(self, host, port):

        # get as number of the address we want to disconnect from
        address = (host, int(port))
        as_number = self.neighbor_ids[address]
        withdraw_routes = self.routing_table.remove_routes_from_neighbor(as_number)

        # see if we have other routes that go to a prefix logged
        advertise_routes = []
        for w in withdraw_routes:
            if w.prefix in self.routing_table.routes:
                temp = self.routing_table.best_prefix_route(w.prefix)
                new_route = copy.deepcopy(temp)
                # only want to advertise new route, if the withdrawn was our best route to a prefix
                if new_route.stops != w.stops:
                    advertise_routes.append(new_route)


        #for a in advertise_routes:
            #print("Advertise Route: {} {}".format(a.prefix, a.stops))
        # check we are connected to the adress specified, then disconnect and update neighbors
        if address in self.connections:
            self.lock.acquire()
            disconnect_socket = self.connections[address]

            #send routes to withdraw for to other neighbors that went through disconnect
            for wr in withdraw_routes:
                self.send_updates("W", wr, address)

            # loop through stored routes
            for ar in advertise_routes:
                #print("Disconnect: Advertise {} {}".format(ar.prefix, ar.stops))
                origin = ar.origin
                # if it locally originated, set to our own addres, so updates can be sent
                if origin == None:
                    origin_address = self.address
                else:
                    origin_address = self.get_address_from_id(origin)

                # shouldn't matter because they only advertise best routes, and would have advertise a local route first
                self.send_updates("A",  ar, origin_address)

            # remove information logged about neighbor
            self.socket_list.remove(disconnect_socket)
            disconnect_socket.close()
            del self.read_buffer[address]
            del self.connections[address]
            del self.neighbor_ids[address]
            del self.connection_type[address]
            self.peer_list.remove(address)
            self.lock.release()


    ######################################################################
    def advertise(self, prefix):

        new_route = route(prefix)
        advertise_route = route(prefix)


        #if we had previous route to prefix that was local, withdraw
        if prefix in self.routing_table.routes:
            original_best = self.routing_table.best_prefix_route(prefix)
            origin = original_best.origin

            if origin != None:
                #print("Withdraw Old best route {} {}".format(original_best.prefix, original_best.stops))
                origin_address = self.get_address_from_id(origin)
                self.send_updates("W", original_best, origin_address)

        self.routing_table.add_route(new_route, __LOCAL__, self.server_address)
        advertise_route.add_origin(self.id)

        new_update = update()
        new_update.encode("A", advertise_route)

        #send to all neighbors
        self.lock.acquire()
        for s in self.socket_list:
            s.send(new_update.packet)

        self.lock.release()

    ######################################################################
    def withdraw(self, prefix):

        # create update of route to prefix through us that says withdraw, and remove route from our routing table
        new_route = route(prefix)
        self.routing_table.withdraw_route(new_route)
        new_route.add_origin(self.id)
        new_update = update()
        new_update.encode("W", new_route)

        #send to all neighbors
        self.lock.acquire()

        for s in self.socket_list:
            s.send(new_update.packet)

        if prefix in self.routing_table.routes:
            original_best = self.routing_table.best_prefix_route(prefix)
            origin = original_best.origin

            if origin != None:
                #print("Advertise Old best route {} {}".format(original_best.prefix, original_best.stops))
                origin_address = self.get_address_from_id(origin)
                self.send_updates("A", original_best, origin_address)

        self.lock.release()

    ######################################################################
    def show_routes(self):

        print("BEGIN ROUTE LIST")
        #self.f.write("Route List: \n")

        q = PriorityQueue()
        for key in self.routing_table.routes:
            p = prefix_object(key)
            route_list = copy.deepcopy(self.routing_table.routes[key])
            q.put((p , route_list))

        while not q.empty():
            route_list = q.get()
            for route in route_list[1]:
                r_str = route.to_string()
                print("{} {}".format(route.prefix, r_str))
                #self.f.write("{} {}\n".format(route.prefix, r_str))

        del q

        print("END ROUTE LIST")


    ######################################################################
    def show_best_route(self, ip):
        options = []

        #find prefixes that correspond to ip and get the best routes to them
        for key in self.routing_table.routes:
            check_prefix = prefix_object(key)
            if check_prefix.compare_ip(ip):
                temp = copy.deepcopy(self.routing_table.best_prefix_route(key))
                options.append(temp)

        if len(options) == 0:
            print("None")
            return

        options.sort()


        # get prefix of first option
        best_route = copy.deepcopy(options[0])
        best_prefix = prefix_object(best_route.prefix)


        #iterate through options to find the longest match rule
        for b in options:
            #self.f.write("{} {}\n".format(b.prefix, b.to_string()))
            check_prefix = prefix_object(b.prefix)
            #print("Current best: {}, Check: {}".format(best_route.len, check_prefix.len))
            if check_prefix.len > best_prefix.len:
                best_route = copy.deepcopy(b)
                best_prefix = check_prefix
                #print("New_best: {}".format(best_prefix.prefix))
        r_str = best_route.to_string()
        del options

        print("{} {}".format(best_route.prefix, r_str))
        #self.f.write("Best route: {} {} for {} \n".format(best_route.prefix, r_str, ip))



    ######################################################################
    def show_peers(self):
        print("BEGIN PEER LIST")
        for address in self.peer_list:
            t = self.connection_type[address]

            if t == __CUSTOMER__:
                peer_type = "customer"
            elif t == __PROVIDER__:
                peer_type = "provider"
            else:
                peer_type = "peer"

            print("{} {}:{}".format(peer_type, address[0], address[1]))
        print("END PEER LIST")


    ######################################################################
    def quit(self):
        self.state = __CONNECTION_CLOSED__
        self.connection_thread.join()
        self.update_thread.join()
        self.socket.close()
        self.f.close()
        del self.threads
        del self.neighbor_ids
        del self.connection_type
        for s in self.socket_list:
            s.close()
        del self.socket_list
        del self.peer_list
        del self.connections





###############################################################################
###############################################################################
if __name__ == "__main__":

    if len(sys.argv) != 3:
        print("Usage: {} <ID> <port>".format(__file__))
        #sys.exit(1)

    bgp = BGP(sys.argv[1], sys.argv[2])



    while bgp.state == __CONNECTION_OPEN__:

        request = input("")
        parameters = request.split(" ")


        if parameters[0] == 'connect':
            node_type = parameters[1]
            i = parameters[2].find(":")
            host = parameters[2][:i]
            #host = "127.0.0.1"
            #port = parameters[2]
            port = parameters[2][i + 1:]

            bgp.connect(node_type, host, port)

        elif parameters[0] == 'disconnect' and len(parameters) == 2:

            host, port = parameters[1].split(":")
            #port = parameters[1]
            bgp.disconnect(host, port)

        elif parameters[0] == 'advertise' and len(parameters) == 2:
            check = parameters[1].split("/")
            if len(check) != 2:
                print("Incorrect parameter")

            prefix = parameters[1]
            bgp.advertise(prefix)

        elif parameters[0] == 'withdraw' and len(parameters) == 2:
            prefix = parameters[1]
            bgp.withdraw(prefix)

        elif parameters[0] == 'routes':
            bgp.show_routes()

        elif parameters[0] == 'best':
            ip = parameters[1]
            bgp.show_best_route(ip)

        elif parameters[0] == 'peers':
            bgp.show_peers()

        elif parameters[0] == 'quit':
            bgp.quit()


        else:
            print("Commands:")
            print("    connect <type> <address>")
            print("    disconnect <address>")
            print("    advertise <prefix>")
            print("    withdraw <prefix>")
            print("    routes")
            print("    best <ip>")
            print("    peers")
            print("    quit")

    del bgp
