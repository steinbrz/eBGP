# eBGP
# Code simulates the protocol of eBGP
# Nodes run by bgp.py {node #} {port number to open on}
# Then can connect or disconnect from other Nodes
# e.g. connect {peer, customer, provider} address:port
# Advertise or withdraw an advertised prefix
# e.g. advertise {prefix}
# prefix is written as address/(subnet mask len)
# e.g. 10.0.0.0/24
# peers will show currently connected neighbors
# routes will show currently known routes
# best {ip address} will show the best route to a provided ip address
# chooses route based on longest prefix matching 
