"""Fixture: planted violations. Every `# expect:` line must be reported, nothing else."""

import json
import numpy as np
import urllib.parse  # expect: sym-single-egress
from urllib.parse import quote  # expect: sym-single-egress
from collections import Counter
from symbiont.records import schema
from . import sibling
from .sibling import thing
import requests  # expect: sym-single-egress
import urllib.request  # expect: sym-single-egress
from urllib import request  # expect: sym-single-egress
from urllib.request import urlopen  # expect: sym-single-egress
from http.client import HTTPConnection  # expect: sym-single-egress
import http.server  # expect: sym-single-egress
import socket  # expect: sym-single-egress
from httpx import post  # expect: sym-single-egress
import ssl  # expect: sym-single-egress
import grpc  # expect: sym-single-egress
import xmlrpc.client  # expect: sym-single-egress
import litellm  # expect: sym-single-egress
import boto3  # expect: sym-single-egress
import ollama  # expect: sym-single-egress
import transformers  # expect: sym-single-egress
import google.generativeai  # expect: sym-single-egress
import asyncio  # expect: sym-single-egress
import ftplib as file_transfer  # expect: sym-single-egress
import multiprocessing.connection  # expect: sym-single-egress
from aiohttp import ClientSession  # expect: sym-single-egress
import selectors  # expect: sym-single-egress
import ctypes  # expect: sym-single-egress
import some_future_sdk  # expect: sym-single-egress
import json, requests  # expect: sym-single-egress
import numpy.linalg
import numpy as np2
import requests.adapters as adapters  # expect: sym-single-egress
