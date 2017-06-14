#
# (C) Copyright 2003-2005 Hewlett-Packard Development Company, L.P.
# (C) Copyright 2006-2007 Novell, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
# Author: Tim Potter <tpot@hp.com>
# Author: Martin Pool <mbp@hp.com>
# Author: Bart Whiteley <bwhiteley@suse.de>
#

"""
Send HTTP/HTTPS requests to a WBEM server.

This module does not know anything about the fact that the data being
transferred in the HTTP request and response is CIM-XML.  It is up to the
caller to provide CIM-XML formatted input data and interpret the result data
as CIM-XML.
"""

import base64
import logging
import os
from pywbemReq import cim_obj
from pywbemReq.cim_types import is_text
import re
import requests
import six

log = logging.getLogger(__name__)

__all__ = ['Error', 'ConnectionError', 'AuthError', 'TimeoutError',
           'HTTPTimeout', 'wbem_request', 'get_object_header']

ca_cert_folder = (
    '/etc/pki/ca-trust/extracted/openssl/ca-bundle.trust.crt',
    '/etc/ssl/certs',
    '/etc/ssl/certificates')


def parse_url(url):
    """Return a tuple of ``(host, port, ssl)`` from the URL specified in the
    ``url`` parameter.

    The returned ``ssl`` item is a boolean indicating the use of SSL, and is
    recognized from the URL scheme (http vs. https). If none of these schemes
    is specified in the URL, the returned value defaults to False
    (non-SSL/http).

    The returned ``port`` item is the port number, as an integer. If there is
    no port number specified in the URL, the returned value defaults to 5988
    for non-SSL/http, and to 5989 for SSL/https.

    The returned ``host`` item is the host portion of the URL, as a string.
    The host portion may be specified in the URL as a short or long host name,
    dotted IPv4 address, or bracketed IPv6 address with or without zone index
    (aka scope ID). An IPv6 address is converted from the RFC6874 URI syntax
    to the RFC4007 text representation syntax before being returned, by
    removing the brackets and converting the zone index (if present) from
    "-eth0" to "%eth0".

    Examples for valid URLs can be found in the test program
    `testsuite/test_cim_http.py`.

    :param url: url string

    :returns: host, port, is ssl

    """
    default_port_http = 5988  # default port for http
    default_port_https = 5989  # default port for https
    default_ssl = False  # default SSL use (for no or unknown scheme)

    # Look for scheme.
    m = re.match(r"^(https?)://(.*)$", url, re.I)
    if m:
        _scheme = m.group(1).lower()
        host_port = m.group(2)
        if _scheme == 'https':
            ssl = True
        else:  # will be 'http'
            ssl = False
    else:
        # The URL specified no scheme (or a scheme other than the expected
        # schemes, but we don't check)
        ssl = default_ssl
        host_port = url

    # Remove trailing path segments, if any.
    # Having URL components other than just slashes (e.g. '#' or '?') is not
    # allowed (but we don't check).
    m = host_port.find("/")
    if m >= 0:
        host_port = host_port[0:m]

    # Look for port.
    # This regexp also works for (colon-separated) IPv6 addresses, because they
    # must be bracketed in a URL.
    m = re.search(r":([0-9]+)$", host_port)
    if m:
        host = host_port[0:m.start(0)]
        port = int(m.group(1))
    else:
        host = host_port
        port = default_port_https if ssl else default_port_http

    # Reformat IPv6 addresses from RFC6874 URI syntax to RFC4007 text
    # representation syntax:
    #   - Remove the brackets.
    #   - Convert the zone index (aka scope ID) from "-eth0" to "%eth0".
    # Note on the regexp below: The first group needs the '?' after '.+' to
    # become non-greedy; in greedy mode, the optional second group would never
    # be matched.
    m = re.match(r"^\[?(.+?)(?:-(.+))?\]?$", host)
    if m:
        # It is an IPv6 address
        host = m.group(1)
        if m.group(2) is not None:
            # The zone index is present
            host += "%" + m.group(2)

    return host, port, ssl


def get_default_ca_certs():
    """
    Try to find out system path with ca certificates. This path is cached and
    returned. If no path is found out, None is returned.
    """
    if not hasattr(get_default_ca_certs, 'path'):
        for path in ca_cert_folder:
            if os.path.exists(path):
                get_default_ca_certs.path = path
                break
        else:
            get_default_ca_certs.path = None
    return get_default_ca_certs.path


def wbem_request(url, data, creds=None, headers=None, ca_certs=None,
                 verify=False, timeout=None):
    data = _normalize_data(data)
    ca_certs = _normalize_ca_certs(verify, ca_certs)
    headers = _normalize_header(headers, creds)

    response = requests.post(url=url, data=data, cert=ca_certs, verify=verify,
                             timeout=timeout, headers=headers)
    if response.status_code != 200:
        log.info(response)
    else:
        log.debug(response)
    return response.text


def get_object_header(obj):
    """Return the HTTP header required to make a CIM operation request
    using the given object.  Return None if the object does not need
    to have a header.
    :param obj: object of the operation.
    """

    # Local name space path

    if is_text(obj):
        return '{}'.format(obj)

    # CIMLocalClassPath

    if isinstance(obj, cim_obj.CIMClassName):
        return '{}:{}'.format(obj.namespace, obj.classname)

    # CIMInstanceName with namespace

    if isinstance(obj, cim_obj.CIMInstanceName) and obj.namespace is not None:
        return '{}'.format(obj)

    raise TypeError(
        "Don't know how to generate HTTP headers for {}".format(obj))


def _normalize_data(data):
    if isinstance(data, six.text_type):
        data = data.encode('utf-8')

    if 'xml version="1.0"' not in data:
        data = '<?xml version="1.0" encoding="utf-8" ?>\n' + data

    return data


def _normalize_ca_certs(verify, ca_certs):
    if verify and ca_certs is None:
        ca_certs = get_default_ca_certs()
    elif not verify:
        ca_certs = None
    return ca_certs


def _normalize_header(header, creds):
    header['Content-type'] = 'application/xml; charset="utf-8"'
    if creds is not None:
        try:
            base64.encodebytes
        except AttributeError:
            base64.encodebytes = base64.encodestring
        header['Authorization'] = 'Basic {}'.format(base64.encodebytes(
            '{}:{}'.format(creds[0], creds[1])).replace('\n', ''))
    return header
