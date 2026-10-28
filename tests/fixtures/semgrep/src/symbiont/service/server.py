"""Fixture: the one listener. Only a literal 127.0.0.1 bind and http.server pass."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socketserver  # expect: sym-service-server-transport
import socket  # expect: sym-service-server-transport
import http.client  # expect: sym-service-server-transport
import urllib.request  # expect: sym-service-server-transport
from symbiont.egress import post_json  # expect: sym-service-server-transport
from symbiont import egress  # expect: sym-service-server-transport
import symbiont.egress  # expect: sym-service-server-transport
import http  # expect: sym-service-server-transport


class Routes(BaseHTTPRequestHandler):
    pass


def listens(port):
    ok = ThreadingHTTPServer(("127.0.0.1", port), Routes)
    ThreadingHTTPServer(("0.0.0.0", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer(("", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer(("::", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer(("::1", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer(("localhost", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer((HOST, port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer((os.environ["SYMBIONT_HOST"], port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer((f"{os.getpid()}", port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer((socket.gethostname(), port), Routes)  # expect: sym-service-server-transport
    ThreadingHTTPServer(server_address=(HOST, port), RequestHandlerClass=Routes)  # expect: sym-service-server-transport
    return ok


def forwards(body):
    post_json(body)  # expect: sym-service-server-transport
    urlopen(body)  # expect: sym-service-server-transport
    socket.create_connection(("127.0.0.1", 1))  # expect: sym-service-server-transport sym-network-subprocess
    http.client.HTTPConnection("127.0.0.1")  # expect: sym-service-server-transport


def rebinds(server):
    server.server_bind()  # expect: sym-service-server-transport


def decodes(raw):
    return json.loads(raw)


async def serves_elsewhere(client_connected):
    return await asyncio.start_server(client_connected, "127.0.0.1", 1)  # expect: sym-network-subprocess
