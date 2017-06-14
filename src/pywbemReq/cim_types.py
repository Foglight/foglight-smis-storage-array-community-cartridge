#
# (C) Copyright 2003,2004 Hewlett-Packard Development Company, L.P.
# (C) Copyright 2006,2007 Novell, Inc.
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
# Author: Bart Whiteley <bwhiteley@suse.de>
#

"""
Types to represent CIM typed values, and related conversion functions.

The following table shows how CIM typed values are represented as Python
objects:

=========================  ===========================
CIM type                   Python type
=========================  ===========================
boolean                    `bool`
char16                     `unicode` or `str`
string                     `unicode` or `str`
string (EmbeddedInstance)  `CIMInstance`
string (EmbeddedObject)    `CIMInstance` or `CIMClass`
datetime                   `CIMDateTime`
reference                  `CIMInstanceName`
uint8                      `Uint8`
uint16                     `Uint16`
uint32                     `Uint32`
uint64                     `Uint64`
sint8                      `Sint8`
sint16                     `Sint16`
sint32                     `Sint32`
sint64                     `Sint64`
real32                     `Real32`
real64                     `Real64`
[] (array)                 `list`
=========================  ===========================

Note that constructors of PyWBEM classes that take CIM typed values as input
may support Python types in addition to those shown above. For example, the
`CIMProperty` class represents CIM datetime values internally as a
`CIMDateTime` object, but its constructor accepts `datetime.timedelta`,
`datetime.datetime`, `str`, and `unicode` objects in addition to
`CIMDateTime` objects.
"""

# This module is meant to be safe for 'import *'.

from __future__ import unicode_literals
from datetime import tzinfo, datetime, timedelta
from past.builtins import basestring, cmp, long
import re
import six

__all__ = ['MinutesFromUTC', 'CIMType', 'CIMDateTime', 'CIMInt', 'Uint8',
           'Sint8', 'Uint16', 'Sint16', 'Uint32', 'Sint32', 'Uint64', 'Sint64',
           'CIMFloat', 'Real32', 'Real64', 'cimtype', 'type_from_name',
           'atomic_to_cim_xml']


class MinutesFromUTC(tzinfo):
    """
    A `datetime.tzinfo` implementation defined using a fixed offset in +/-
    minutes from UTC.
    """

    def __init__(self, offset, *args, **kwargs):
        """
        Initialize the `MinutesFromUTC` object from a timezone offset.

        :Parameters:

          offset : `int`
            Timezone offset in +/- minutes from UTC, where a positive value
            indicates minutes east of UTC, and a negative value indicates
            minutes west of UTC.
        """
        super(MinutesFromUTC, self).__init__(*args, **kwargs)
        self.__offset = timedelta(minutes=offset)

    def utcoffset(self, _):
        """
        Implement the `datetime.tzinfo.utcoffset` method by returning
        the timezone offset as a `datetime.timedelta` object.
        :param _: not used
        """
        return self.__offset

    def dst(self, _):
        """
        Implement the `datetime.tzinfo.dst` method by returning
        a DST value of 0 as a `datetime.timedelta` object.
        :param _: not used
        """
        return timedelta(0)


class CIMType(object):
    """Base type for numeric and datetime CIM types."""
    cimtype = None


class CIMDateTime(CIMType):
    """
    A value of CIM type datetime.

    The object represents either a timezone-aware point in time, or a time
    interval.
    """

    date_pattern = re.compile(
        r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.'
        r'(\d{6})([+|-])(\d{3})')

    tv_pattern = re.compile(
        r'^(\d{8})(\d{2})(\d{2})(\d{2})\.(\d{6})(:)(000)')

    def __init__(self, dtarg):
        """
        Initialize the `CIMDateTime` object from different types of input
        object.

        :Parameters:

          dtarg
            The input object, as one of the following types:
            An `str` or `unicode` object will be interpreted as CIM datetime
            format (see DSP0004) and will result in a point in time or a time
            interval.
            A `datetime.datetime` object must be timezone-aware and will
            result in a point in time.
            A `datetime.timedelta` object will result in a time interval.
            Another `CIMDateTime` object will be copied.

        :Raises:
          :raise ValueError:
          :raise TypeError:
        """
        self.cimtype = 'datetime'
        self._timedelta = None
        self._datetime = None
        if isinstance(dtarg, basestring):
            s = self.date_pattern.search(dtarg)
            if s is not None:
                g = s.groups()
                offset = int(g[8])
                if g[7] == '-':
                    offset = -offset
                try:
                    self._datetime = datetime(int(g[0]), int(g[1]),
                                              int(g[2]), int(g[3]),
                                              int(g[4]), int(g[5]),
                                              int(g[6]),
                                              MinutesFromUTC(offset))
                except ValueError as exc:
                    raise ValueError('dtarg argument "{}" has invalid field '
                                     'values for CIM datetime timestamp '
                                     'format: {}'.format(dtarg, exc))
            else:
                s = self.tv_pattern.search(dtarg)
                if s is not None:
                    g = s.groups()
                    # Because the input values are limited by the matched
                    # pattern, timedelta() never throws any exception.
                    self._timedelta = timedelta(days=int(g[0]),
                                                hours=int(g[1]),
                                                minutes=int(g[2]),
                                                seconds=int(g[3]),
                                                microseconds=int(g[4]))
                else:
                    raise ValueError('dtarg argument "{}" has an invalid CIM '
                                     'datetime format'.format(dtarg))
        elif isinstance(dtarg, datetime):
            self._datetime = dtarg
        elif isinstance(dtarg, timedelta):
            self._timedelta = dtarg
        elif isinstance(dtarg, CIMDateTime):
            self._datetime = dtarg._datetime
            self._timedelta = dtarg._timedelta
        else:
            raise TypeError('dtarg argument "{}" has an invalid type: {} '
                            '(expected datetime, timedelta, string, or '
                            'CIMDateTime)'.format(dtarg, type(dtarg)))

    @property
    def minutes_from_utc(self):
        """
        The timezone offset of a point in time object as +/- minutes from UTC.

        A positive value of the timezone offset indicates minutes east of UTC,
        and a negative value indicates minutes west of UTC.

        0, if the object represents a time interval.
        """
        offset = 0
        if self._datetime is not None:
            if self._datetime.utcoffset() is not None:
                offset = self._datetime.utcoffset().seconds / 60
                if self._datetime.utcoffset().days == -1:
                    offset = -(60 * 24 - offset)
        return offset

    @property
    def datetime(self):
        """
        The point in time represented by the object, as a `datetime.datetime`
        object.

        `None` if the object represents a time interval.
        """
        return self._datetime

    @property
    def timedelta(self):
        """
        The time interval represented by the object, as a `datetime.timedelta`
        object.

        `None` if the object represents a point in time.
        """
        return self._timedelta

    @property
    def is_interval(self):
        """
        A boolean indicating whether the object represents a time interval
        (`True`) or a point in time (`False`).
        """
        return self._timedelta is not None

    @staticmethod
    def get_local_utcoffset():
        """
        Return the timezone offset of the current local timezone from UTC.

        A positive value indicates minutes east of UTC, and a negative
        value indicates minutes west of UTC.
        """
        utc = datetime.utcnow()
        local = datetime.now()
        if local < utc:
            return - int(float((utc - local).seconds) / 60 + .5)
        else:
            return int(float((local - utc).seconds) / 60 + .5)

    @classmethod
    def now(cls, tzi=None):
        """
        Factory method that returns a new `CIMDateTime` object representing
        the current date and time.

        The optional timezone information is used to convert the CIM datetime
        value into the desired timezone. That does not change the point in time
        that is represented by the value, but it changes the value of the
        `hhmmss` components of the CIM datetime value to compensate for changes
        in the timezone offset component.

        :param tzi: `datetime.tzinfo`
            Timezone information. `None` means that the current local timezone
            is used. The `datetime.tzinfo` object may be a `MinutesFromUTC`
            object.

        :returns
            A new `CIMDateTime` object representing the current date and time.
        """
        if tzi is None:
            tzi = MinutesFromUTC(cls.get_local_utcoffset())
        return cls(datetime.now(tzi))

    @classmethod
    def fromtimestamp(cls, ts, tzi=None):
        """
        Factory method that returns a new `CIMDateTime` object from a POSIX
        timestamp value and optional timezone information.

        A POSIX timestamp value is the number of seconds since 1970-01-01
        00:00:00 UTC. Thus, a POSIX timestamp value is unambiguous w.r.t. the
        timezone.

        The optional timezone information is used to convert the CIM datetime
        value into the desired timezone. That does not change the point in time
        that is represented by the value, but it changes the value of the
        `hhmmss` components of the CIM datetime value to compensate for changes
        in the timezone offset component.

        :param tzi: `datetime.tzinfo`
            Timezone information. `None` means that the current local timezone
            is used. The `datetime.tzinfo` object may be a `MinutesFromUTC`
            object.
        :param ts: `int`
            POSIX timestamp value.

        :returns
            A new `CIMDateTime` object representing the specified point in
            time.
        """
        if tzi is None:
            tzi = MinutesFromUTC(cls.get_local_utcoffset())
        return cls(datetime.fromtimestamp(ts, tzi))

    def __str__(self):
        """
        Return a string representing the object in CIM datetime format.
        """
        if self.is_interval:
            hour = self.timedelta.seconds / 3600
            minute = (self.timedelta.seconds - hour * 3600) / 60
            second = self.timedelta.seconds - hour * 3600 - minute * 60
            return '%08d%02d%02d%02d.%06d:000' % \
                   (self.timedelta.days, hour, minute, second,
                    self.timedelta.microseconds)
        else:
            offset = self.minutes_from_utc
            sign = '+'
            if offset < 0:
                sign = '-'
                offset = -offset
            return '%d%02d%02d%02d%02d%02d.%06d%s%03d' % \
                   (self.datetime.year, self.datetime.month,
                    self.datetime.day, self.datetime.hour,
                    self.datetime.minute, self.datetime.second,
                    self.datetime.microsecond, sign, offset)

    def __repr__(self):
        return '%s(\'%s\')' % (self.__class__.__name__, str(self))

    def __getstate__(self):
        return str(self)

    def __setstate__(self, arg):
        self.__init__(arg)

    def __cmp__(self, other):
        if self is other:
            return 0
        elif not isinstance(other, CIMDateTime):
            return 1
        datetime_eq = cmp(self.datetime, other.datetime)
        if self.timedelta is not None and other.timedelta is not None:
            timedelta_eq = cmp(self.timedelta, other.timedelta)
        elif self.timedelta is None and other.timedelta is None:
            timedelta_eq = 0
        else:
            timedelta_eq = 1

        return datetime_eq or timedelta_eq

    def __lt__(self, other):
        return self.__cmp__(other)

    def __eq__(self, other):
        return self.__cmp__(other) == 0


class CIMInt(CIMType, long):
    """Base type for integer CIM types."""


class Uint8(CIMInt):
    """A value of CIM type uint8."""
    cimtype = 'uint8'


class Sint8(CIMInt):
    """A value of CIM type sint8."""
    cimtype = 'sint8'


class Uint16(CIMInt):
    """A value of CIM type uint16."""
    cimtype = 'uint16'


class Sint16(CIMInt):
    """A value of CIM type sint16."""
    cimtype = 'sint16'


class Uint32(CIMInt):
    """A value of CIM type uint32."""
    cimtype = 'uint32'


class Sint32(CIMInt):
    """A value of CIM type sint32."""
    cimtype = 'sint32'


class Uint64(CIMInt):
    """A value of CIM type uint64."""
    cimtype = 'uint64'


class Sint64(CIMInt):
    """A value of CIM type sint64."""
    cimtype = 'sint64'


# CIM float types

class CIMFloat(CIMType, float):
    """Base type for real (floating point) CIM types."""


class Real32(CIMFloat):
    """A value of CIM type real32."""
    cimtype = 'real32'


class Real64(CIMFloat):
    """A value of CIM type real64."""
    cimtype = 'real64'


def cimtype(obj):
    """
    Return the CIM type name of a value, as a string.

    For an array, the type is determined from the first array element because
    CIM arrays must be homogeneous. If the array is empty, ValueError is
    raised.

    If the type of the value is not a CIM type, TypeError is raised.

    :param obj: CIM typed value
        The value whose CIM type name is returned.

    :return
        The CIM type name of the value, as a string.

    :raise TypeError:
        Type is not a CIM type.

    :raise ValueError:
        Cannot determine CIM type from empty array.
    """
    if isinstance(obj, CIMType):
        return obj.cimtype
    if isinstance(obj, bool):
        return 'boolean'
    if isinstance(obj, basestring):
        return 'string'
    if isinstance(obj, list):
        if len(obj) == 0:
            raise ValueError("Cannot determine CIM type from empty array")
        return cimtype(obj[0])
    if isinstance(obj, (datetime, timedelta)):
        return 'datetime'
    raise TypeError("Type {} of this value is not a CIM type: {}".format
                    (type(obj), obj))


_TYPE_FROM_NAME = {
    'boolean': bool,
    'string': str,
    'char16': str,
    'datetime': CIMDateTime,
    # 'reference' covered at run time
    'uint8': Uint8,
    'uint16': Uint16,
    'uint32': Uint32,
    'uint64': Uint64,
    'sint8': Sint8,
    'sint16': Sint16,
    'sint32': Sint32,
    'sint64': Sint64,
    'real32': Real32,
    'real64': Real64,
}


def type_from_name(type_name):
    """
    Return the Python type object for a given CIM type name.

    For example, type name `'uint8'` will return type `Uint8`.

    :param type_name: type_name : `str` or `unicode`
        The simple (=non-array) CIM type name (e.g. `'uint8'` or
        `'reference'`).

    :returns
        The Python type object for the CIM type (e.g. `Uint8` or
        `CIMInstanceName`).

    :raise ValueError:
        Unknown CIM type name.
    """
    if type_name == 'reference':
        # move import to run time to avoid circular imports
        from pywbemReq import cim_obj
        return cim_obj.CIMInstanceName
    try:
        type_obj = _TYPE_FROM_NAME[type_name]
    except KeyError:
        raise ValueError("Unknown CIM type name: %r" % type_name)
    return type_obj


def atomic_to_cim_xml(obj):
    """
    Convert a value of an atomic scalar CIM type to a CIM-XML unicode string
    and return that string.

    :param obj: CIM typed value.
        The CIM typed value`, including `None`. Must be a scalar. Must be an
        atomic type (i.e. not `CIMInstance` or `CIMClass`).

    :returns

        A unicode string in CIM-XML value format representing the CIM typed
        value. For a value of `None`, `None` is returned.
    """

    # TODO: Verify whether we can change this function to raise a ValueError in
    # case the value is not CIM typed.

    if isinstance(obj, bool):
        if obj:
            return u"true"
        else:
            return u"false"
    elif isinstance(obj, CIMDateTime):
        return str(obj)
    elif isinstance(obj, datetime):
        return str(CIMDateTime(obj))
    elif obj is None:
        return obj
    elif cimtype(obj) == 'real32':
        return u'%.8E' % obj
    elif cimtype(obj) == 'real64':
        return u'%.16E' % obj
    # elif isinstance(obj, str):
    #     return obj.decode('utf-8')
    else:  # e.g. unicode, int
        return str(obj)


def is_int(value):
    return isinstance(value, six.integer_types)


def is_number(value):
    return isinstance(value, six.integer_types + (float,))


def is_text(value):
    return isinstance(value, six.string_types)


def is_number_or_text(value):
    return is_number(value) or is_text(value)


def is_number_or_bool(value):
    return is_number(value) or isinstance(value, bool)


def is_text_or_bool(value):
    return is_text(value) or isinstance(value, bool)


def is_cim_type(value):
    return isinstance(value, CIMType)
