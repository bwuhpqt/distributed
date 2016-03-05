from __future__ import print_function, division, absolute_import

from collections import defaultdict
import json
import logging

from toolz import countby
from tornado import web, gen
from tornado.httpclient import AsyncHTTPClient

from .core import RequestHandler, MyApp, Resources, Proxy
from ..utils import key_split
from ..compatibility import unicode


logger = logging.getLogger(__name__)


def ensure_string(s):
    if not isinstance(s, unicode):
        s = s.decode()
    return s


class Info(RequestHandler):
    """ Basic info about the scheduler """
    def get(self):
        self.write({'ncores': self.server.ncores,
                    'status': self.server.status})


class Processing(RequestHandler):
    """ Active tasks on each worker """
    def get(self):
        resp = {addr: [ensure_string(key_split(t)) for t in tasks]
                for addr, tasks in self.server.processing.items()}
        self.write(resp)


class Broadcast(RequestHandler):
    """ Send call to all workers, collate their responses """
    @gen.coroutine
    def get(self, rest):
        addresses = [addr.split(':') + [d['services']['http']]
                     for addr, d in self.server.worker_info.items()
                     if 'http' in d['services']]
        client = AsyncHTTPClient()
        responses = {'%s:%s' % (ip, tcp_port): client.fetch("http://%s:%s/%s" %
                                                  (ip, http_port, rest))
                     for ip, tcp_port, http_port in addresses}
        responses2 = yield responses
        responses3 = {k: json.loads(v.body.decode())
                      for k, v in responses2.items()}
        self.write(responses3)  # TODO: capture more data of response


class MemoryLoad(RequestHandler):
    """The total amount of data held in memory by workers"""
    def get(self):
        self.write({worker: sum(self.server.nbytes[k] for k in keys)
                   for worker, keys in self.server.has_what.items()})


class MemoryLoadByKey(RequestHandler):
    """The total amount of data held in memory by workers"""
    def get(self):
        out = {}
        for worker, keys in self.server.has_what.items():
            d = defaultdict(lambda: 0)
            for key in keys:
                d[key_split(key)] += self.server.nbytes[key]
            out[worker] = {k: v for k, v in d.items()}
        self.write(out)


class Status(RequestHandler):
    """ Lots of information about all the workers """
    def get(self):
        workers = list(self.server.ncores)

        bytes= {w: sum(self.server.nbytes[k]
                       for k in self.server.has_what[w])
                  for w in workers}
        processing = {w: countby(key_split, tasks)
                    for w, tasks in self.server.processing.items()}

        result = {'address': self.server.address,
                  'ncores': self.server.ncores,
                  'bytes': bytes, 'processing': processing,
                  'tasks': len(self.server.tasks),
                  'in-memory': len(self.server.who_has),
                  'ready': len(self.server.ready)
                         + sum(map(len, self.server.stacks.values())),
                  'waiting': len(self.server.waiting),
                  'failed': len(self.server.exceptions_blame)}

        self.write(result)


def HTTPScheduler(scheduler):
    application = MyApp(web.Application([
        (r'/info.json', Info, {'server': scheduler}),
        (r'/resources.json', Resources, {'server': scheduler}),
        (r'/processing.json', Processing, {'server': scheduler}),
        (r'/proxy/([\w.-]+):(\d+)/(.+)', Proxy),
        (r'/broadcast/(.+)', Broadcast, {'server': scheduler}),
        (r'/status.json', Status, {'server': scheduler}),
        (r'/', Status, {'server': scheduler}),
        (r'/memory-load.json', MemoryLoad, {'server': scheduler}),
        (r'/memory-load-by-key.json', MemoryLoadByKey, {'server': scheduler}),
        ]))
    return application
