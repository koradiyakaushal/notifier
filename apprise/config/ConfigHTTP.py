# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 Chris Caron <lead2gold@gmail.com>
# All rights reserved.
#
# This code is licensed under the MIT License.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files(the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions :
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import re
import six
import requests
from .ConfigBase import ConfigBase
from ..common import ConfigFormat

# Support YAML formats
# text/yaml
# text/x-yaml
# application/yaml
# application/x-yaml
MIME_IS_YAML = re.compile('(text|application)/(x-)?yaml', re.I)

# Support TEXT formats
# text/plain
# text/html
MIME_IS_TEXT = re.compile('text/(plain|html)', re.I)


class ConfigHTTP(ConfigBase):
    """
    A wrapper for HTTP based configuration sources
    """

    # The default descriptive name associated with the Notification
    service_name = 'HTTP'

    # The default protocol
    protocol = 'http'

    # The default secure protocol
    secure_protocol = 'https'

    # The maximum number of seconds to wait for a connection to be established
    # before out-right just giving up
    connection_timeout_sec = 5.0

    # If an HTTP error occurs, define the number of characters you still want
    # to read back.  This is useful for debugging purposes, but nothing else.
    # The idea behind enforcing this kind of restriction is to prevent abuse
    # from queries to services that may be untrusted.
    max_error_buffer_size = 2048

    def __init__(self, headers=None, **kwargs):
        """
        Initialize HTTP Object

        headers can be a dictionary of key/value pairs that you want to
        additionally include as part of the server headers to post with

        """
        super(ConfigHTTP, self).__init__(**kwargs)

        if self.secure:
            self.schema = 'https'

        else:
            self.schema = 'http'

        self.fullpath = kwargs.get('fullpath')
        if not isinstance(self.fullpath, six.string_types):
            self.fullpath = '/'

        self.headers = {}
        if headers:
            # Store our extra headers
            self.headers.update(headers)

        return

    def url(self):
        """
        Returns the URL built dynamically based on specified arguments.
        """

        # Define any arguments set
        args = {
            'encoding': self.encoding,
        }

        if self.config_format:
            # A format was enforced; make sure it's passed back with the url
            args['format'] = self.config_format

        # Append our headers into our args
        args.update({'+{}'.format(k): v for k, v in self.headers.items()})

        # Determine Authentication
        auth = ''
        if self.user and self.password:
            auth = '{user}:{password}@'.format(
                user=self.quote(self.user, safe=''),
                password=self.quote(self.password, safe=''),
            )
        elif self.user:
            auth = '{user}@'.format(
                user=self.quote(self.user, safe=''),
            )

        default_port = 443 if self.secure else 80

        return '{schema}://{auth}{hostname}{port}/?{args}'.format(
            schema=self.secure_protocol if self.secure else self.protocol,
            auth=auth,
            hostname=self.host,
            port='' if self.port is None or self.port == default_port
                 else ':{}'.format(self.port),
            args=self.urlencode(args),
        )

    def read(self, **kwargs):
        """
        Perform retrieval of the configuration based on the specified request
        """

        # prepare XML Object
        headers = {
            'User-Agent': self.app_id,
        }

        # Apply any/all header over-rides defined
        headers.update(self.headers)

        auth = None
        if self.user:
            auth = (self.user, self.password)

        url = '%s://%s' % (self.schema, self.host)
        if isinstance(self.port, int):
            url += ':%d' % self.port

        url += self.fullpath

        self.logger.debug('HTTP POST URL: %s (cert_verify=%r)' % (
            url, self.verify_certificate,
        ))

        # Prepare our response object
        response = None

        # Where our request object will temporarily live.
        r = None

        # Always call throttle before any remote server i/o is made
        self.throttle()

        try:
            # Make our request
            r = requests.post(
                url,
                headers=headers,
                auth=auth,
                verify=self.verify_certificate,
                timeout=self.connection_timeout_sec,
                stream=True,
            )

            if r.status_code != requests.codes.ok:
                status_str = \
                    ConfigBase.http_response_code_lookup(r.status_code)
                self.logger.error(
                    'Failed to get HTTP configuration: '
                    '{}{} error={}.'.format(
                        status_str,
                        ',' if status_str else '',
                        r.status_code))

                # Display payload for debug information only; Don't read any
                # more than the first X bytes since we're potentially accessing
                # content from untrusted servers.
                if self.max_error_buffer_size > 0:
                    self.logger.debug(
                        'Response Details:\r\n{}'.format(
                            r.content[0:self.max_error_buffer_size]))

                # Close out our connection if it exists to eliminate any
                # potential inefficiencies with the Request connection pool as
                # documented on their site when using the stream=True option.
                r.close()

                # Return None (signifying a failure)
                return None

            # Store our response
            if self.max_buffer_size > 0 and \
                    r.headers['Content-Length'] > self.max_buffer_size:

                # Provide warning of data truncation
                self.logger.error(
                    'HTTP config response exceeds maximum buffer length '
                    '({}KB);'.format(int(self.max_buffer_size / 1024)))

                # Close out our connection if it exists to eliminate any
                # potential inefficiencies with the Request connection pool as
                # documented on their site when using the stream=True option.
                r.close()

                # Return None - buffer execeeded
                return None

            else:
                # Store our result
                response = r.content

                # Detect config format based on mime if the format isn't
                # already enforced
                content_type = r.headers.get(
                    'Content-Type', 'application/octet-stream')
                if self.config_format is None and content_type:
                    if MIME_IS_YAML.match(content_type) is not None:

                        # YAML data detected based on header content
                        self.default_config_format = ConfigFormat.YAML

                    elif MIME_IS_TEXT.match(content_type) is not None:

                        # TEXT data detected based on header content
                        self.default_config_format = ConfigFormat.TEXT

                    # else do nothing; fall back to whatever default is
                    # already set.

        except requests.RequestException as e:
            self.logger.warning(
                'A Connection error occured retrieving HTTP '
                'configuration from %s.' % self.host)
            self.logger.debug('Socket Exception: %s' % str(e))

            # Return None (signifying a failure)
            return None

        # Close out our connection if it exists to eliminate any potential
        # inefficiencies with the Request connection pool as documented on
        # their site when using the stream=True option.
        r.close()

        # Return our response object
        return response

    @staticmethod
    def parse_url(url):
        """
        Parses the URL and returns enough arguments that can allow
        us to substantiate this object.

        """
        results = ConfigBase.parse_url(url)

        if not results:
            # We're done early as we couldn't load the results
            return results

        # Add our headers that the user can potentially over-ride if they wish
        # to to our returned result set
        results['headers'] = results['qsd-']
        results['headers'].update(results['qsd+'])

        return results
