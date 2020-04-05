# -*- coding: utf-8 -*-
import traceback
import time
import requests
import json

from beaver.transports.base_transport import BaseTransport
from beaver.transports.exception import TransportException


class HttpTransport(BaseTransport):

    def __init__(self, beaver_config, logger=None):
        super(HttpTransport, self).__init__(beaver_config, logger=logger)

        self._url = beaver_config.get('http_url')
        self._logger.info('Initializing with url of: {0}'.format(self._url))
        self._is_valid = False

        self._connect()

    def _connect(self):
        wait = -1
        while True:
            wait += 1
            time.sleep(wait)
            if wait == 20:
                return False

            if wait > 0:
                self._logger.info('Retrying connection, attempt {0}'.format(wait + 1))

            try:
                #check for a 200 on the url
                self._logger.info('connect: {0}'.format(self._url))
                r = requests.get(self._url)
            except Exception as e:
                self._logger.error('Exception caught validating url connection: ' + str(e))
            else:
                self._logger.info('Connection validated')
                self._is_valid = True
                return True

    def reconnect(self):
        self._connect()

    def invalidate(self):
        """Invalidates the current transport"""
        super(HttpTransport, self).invalidate()
        return False

    def callback(self, filename, lines, **kwargs):
        timestamp = self.get_timestamp(**kwargs)
        if kwargs.get('timestamp', False):
            del kwargs['timestamp']

        try:
            for line in lines:
                #escape any tab in the message field, assuming json payload
                jsonline = self.format(filename, line, timestamp, **kwargs)
                edata = jsonline.replace('\t', '\\t')
                self._logger.debug('writing to : {0}'.format(self._url))
                self._logger.debug('writing data: {0}'.format(edata))
                
                try:
                    isjson = json.loads(edata)
                except ValueError:
                    headers = {'content-type': 'application/x-www-form-urlencoded'}
                else:
                    headers = {'content-type': 'application/json'}
                
                r = requests.post(url=self._url, headers=headers, data=edata)
                
                self._logger.info('POST Status {0} - {1}'.format(r.status_code,headers))
                
                if r.status_code >= 200 and r.status_code < 300:
                    res = r.content
                else:
                    self._logger.error('Post returned non 2xx http status: {0}/{1}'.format(r.status_code, r.reason))
        except Exception as e:
            self._logger.error('Exception caught in urlopen connection: ' + str(e))
