import time
from enum import Enum
from typing import Optional, Union, List, Any
from rpcudp.protocol import RPCProtocol

from .node import DHTNode
from .routing import RoutingTable, DHTID, DHTValue, DHTExpirationTime
from ..utils import Hostname, Port, Tuple, Endpoint


class KademliaProtocol(RPCProtocol):
    """
    A protocol that allows DHT nodes to request keys/neighbors from other DHT nodes.
    As a side-effect, KademliaProtocol also maintains a routing table as described in
    https://pdos.csail.mit.edu/~petar/papers/maymounkov-kademlia-lncs.pdf

    Node: the rpc_* methods defined in this class will be automatically exposed to other DHT nodes,
     for instance, def rpc_ping can be called as protocol.ping() from a remote machine
     Read more: https://github.com/bmuller/rpcudp/tree/master/rpcudp
    """

    def __init__(self, node: DHTNode, bucket_size: int, modulo: int,
                 num_neighbors: int, staleness_timeout=Union[float, int]):
        self.node, self.bucket_size, self.num_neighbors = node, bucket_size, num_neighbors
        self.routing_table = RoutingTable(node, bucket_size, modulo, staleness_timeout)

    def rpc_ping(self, sender: Endpoint, sender_id: DHTID) -> DHTID:
        """ Some dht node wants us to add it to our routing table. """
        self.routing_table.register_request_from(sender, sender_id)
        return self.node.id

    async def call_ping(self, recipient: Endpoint) -> Optional[DHTID]:
        """ Get recipient's node id and add him to the routing table. If recipient doesn't respond, return None """
        responded, recipient_node_id = await self.ping(recipient, self.node.id)
        self.routing_table.register_request_to(recipient, recipient_node_id, responded=responded)
        return recipient_node_id

    def rpc_store(self, sender: Endpoint, sender_id: DHTID,
                  key: DHTID, value: DHTValue, expiration_time: DHTExpirationTime) -> Tuple[bool, DHTID]:
        """ Some node wants us to store this (key, value) pair """
        self.routing_table.register_request_from(sender, sender_id)
        store_accepted = self.node.store(key, value, expiration_time)
        return store_accepted, self.node.id

    async def call_store(self, recipient: Endpoint, key: DHTID, value: DHTValue,
                         expiration_time: DHTExpirationTime) -> Optional[bool]:
        """
        Ask a recipient to store (key, value) pair until expiration time or update their older value
        :returns: True if value was accepted, False if it was rejected (recipient has newer value), None if no response
        """
        responded, response = await self.store(recipient, self.node.id, key, value, expiration_time)
        status, recipient_node_id = response if responded else (False, None)
        self.routing_table.register_request_to(recipient, recipient_node_id, responded=responded)
        return response if responded else False

    def rpc_find_node(self, sender: Endpoint, sender_id: DHTID,
                      key_node: DHTID) -> Tuple[List[Tuple[DHTID, Endpoint]], DHTID]:
        """
        Someone wants to find :key_node: in the DHT. Give him k nearest neighbors from our routing table
        :returns: a list of pairs (node_id, address) of :num_neighbors: nearest to key_node according to XOR distance,
         also returns our own node id for routing table maintenance
        """
        self.routing_table.register_request_from(sender, sender_id)
        if key_node in self.routing_table:
            return [(key_node, self.routing_table[key_node])], self.node.id
        neighbor_ids = self.routing_table.get_nearest_neighbors(key_node, k=self.num_neighbors, exclude=sender_id)
        return [(neighbor_id, self.routing_table[neighbor_id]) for neighbor_id in neighbor_ids], self.node_id

    def call_find_node(self, recipient: Endpoint, key_node: DHTID) -> List[Tuple[DHTID, Endpoint]]:
        """
        Ask a recipient to give you nearest neighbors to key_node. If recipient knows key_node directly,
         it will be returned as first of the neighbors; if recipient does not respond, return empty list.
        :returns: a list of pairs (node id, address) as per Section 2.3 of the paper
        """
        responded, response = await self.find_node(recipient, self.node.id, key_node)
        neighbors, recipient_node_id = response if responded else ([], None)
        self.routing_table.register_request_to(recipient, recipient_node_id, responded=responded)
        return neighbors

    def rpc_find_value(self, sender: Endpoint, sender_id: DHTID, key: DHTID) -> \
            Tuple[Optional[DHTValue], Optional[DHTExpirationTime], List[Tuple[DHTID, Endpoint]], DHTID]:
        """
        Someone wants to find value corresponding to key. If we have the value, return the value and its expiration time
        In any case, return :num_neighbors: nearest neighbors to that node.
        Note: this is a deviation from Section 2.3 of the paper, original kademlia returner EITHER value OR neighbors
        :returns: (value or None if we have no value, nearest neighbors, our own dht id)
        """
        return tuple(self.node.get(key)) + self.rpc_find_node(sender, sender_id, key)

    def call_find_value(self, recipient: Endpoint, key: DHTID) -> \
            Tuple[Optional[DHTValue], Optional[DHTExpirationTime], List[Tuple[DHTID, Endpoint]]]:
        """
        Ask a recipient to give you the value, if it has one, or nearest neighbors to your key.
        :returns: (optional value, optional expiration time, and neighbors)
         value: whatever was the latest value stored by the recepient with that key (see DHTNode contract)
         expiration time: expiration time of the returned value, None if no value was found
         neighbors:  a list of pairs (node id, address) as per Section 2.3 of the paper;
        Note: if no response, returns None, None, []
        """
        responded, response = await self.find_value(recipient, self.node.id, key)
        value, expiration_time, neighbors, recipient_node_id = response if responded else (None, None, [], None)
        self.routing_table.register_request_to(recipient, recipient_node_id, responded=responded)
        return value, expiration_time, neighbors
