"""
clock.py

A suite of useful clock/time related functions.

Patrick Lazarus, Nov 20th, 2009
"""
import types
import numpy as np

from . import calendar


def JD_to_GST(JD):
    """Given Julian Day (JD) return Greenwich mean sidereal time
        in hours.

        Follow section 12 of Duffet-Smith's "Practical Astronomy
            with your Calculator", 3rd Ed.
    """
    JD = np.array(JD)

    # Time of day
    days = (JD-0.5) % 1
    hours = days*24

    JD0 = JD-days
    T = (JD0 - np.array(2451545.0))/np.array(36525.0)
    print(T)
    T0 = 6.697374558 + (2400.051336*T) + (0.000025862*T**2)
    print(T0)
    # Reduce to range 0-24
    T0 = T0 % 24

    UT = hours*1.002737909

    GST = UT + T0
    print(GST)
    GST = GST % 24
    return GST


def MJD_to_GST(MJD):
    """Given Julian Day (JD) return Greenwich mean sidereal time
        in hours.

        Converts MJD to JD and calls JD_to_GST(...)
    """
    JD = calendar.MJD_to_JD(MJD)
    return JD_to_GST(JD)


def MJD_lon_to_LST(MJD, lon):
    """Given the longitude of an observer return the LST
        at a given MJD.

        Inputs:
            MJD: The MJD to consider.
            lon: The longitude of the observer (in degrees).
                NOTE: longitudes West should be negative.
                    longitudes East should be positive.

        Output:
            LST: The local sidereal time for the observer (in hours).
    """
    # Get Greenwich mean sidereal time
    GST = MJD_to_GST(MJD)

    lon_hours = lon/15.0

    LST = GST + lon_hours
    LST = LST % 24.0

    return LST


def JD_to_mstUT_deg(JD):
    """Given Julian Day (JD) return mean sidereal time (UT)
        in degrees.
    """
    JD = np.array(JD)
    T = (JD - np.array(2451545.0))/np.array(36525.0)
    print(T)
    mst_deg = np.array(280.46061837) + \
        np.array(360.98564736629)*(JD - np.array(2451545.0)) + \
        np.array(0.000387933)*np.power(T, 2) - \
        np.power(T, 3)/np.array(38710000.0)
    return mst_deg


def MJD_to_mstUT_deg(MJD):
    """Given Modified Julian Day (MJD) return mean sidereal time (UT)
        in degrees.
    """
    JD = MJD_to_JD(MJD)
    return JD_to_mstUT_deg(JD)
