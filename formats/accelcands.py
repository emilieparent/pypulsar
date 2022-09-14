"""
Interface to parse *.accelcands files, combined and 
sifted candidates produced by accelsearch for survey 
pointings.

Patrick Lazarus, Dec. 8, 2010
"""

import os.path
import sys
import re
import types


dmhit_re = re.compile(r'^ *DM= *(?P<dm>[^ ]*) *SNR= *(?P<snr>[^ ]*) *' \
                      r'(Sigma= *(?P<sigma>[^ ]*) *)?\** *$')
candinfo_re = re.compile(r'^(?P<accelfile>.*):(?P<candnum>\d*) *(?P<dm>[^ ]*)' \
                         r' *(?P<snr>[^ ]*) *(?P<sigma>[^ ]*) *(?P<numharm>[^ ]*)' \
                         r' *(?P<ipow>[^ ]*) *(?P<cpow>[^ ]*) *(?P<period>[^ ]*)' \
                         r' *(?P<r>[^ ]*) *(?P<z>[^ ]*) *\((?P<numhits>\d*)\)$')


class Candidate(object):
    """Object to represent candidates as they are listed
        in *.accelcands files.
    """
    def __init__(self, accelfile, candnum, dm, snr, sigma, numharm, \
                        ipow, cpow, period, r, z, *args, **kwargs):
        self.accelfile = accelfile
        self.candnum = int(candnum)
        self.dm = float(dm)
        self.snr = float(snr)
        self.sigma = float(sigma)
        self.numharm = int(numharm)
        self.ipow = float(ipow)
        self.cpow = float(cpow)
        self.period = float(period)
        self.r = float(r)
        self.z = float(z)
        self.dmhits = []

    def add_dmhit(self, dm, snr, sigma=None):
        self.dmhits.append(DMHit(dm, snr, sigma))

    def __str__(self):
        cand = self.accelfile + ':' + repr(self.candnum)
        result = "%-65s   %7.2f  %6.2f  %6.2f  %s   %7.1f  " \
                 "%7.1f  %12.6f  %10.2f  %8.2f  (%d)\n" % \
            (cand, self.dm, self.snr, self.sigma, \
                "%2d".center(7) % self.numharm, self.ipow, \
                self.cpow, self.period*1000.0, self.r, self.z, \
                len(self.dmhits))
        for dmhit in self.dmhits:
            result += str(dmhit)
        return result


class DMHit(object):
    """Object to represent a DM hit of an accelcands candidate.
    """
    def __init__(self, dm, snr, sigma=None):
        self.dm = float(dm)
        self.snr = float(snr)
        if sigma is not None:
            self.sigma = float(sigma)
        else:
            self.sigma = None

    def __str__(self):
        if self.sigma is None:
            result = "  DM=%6.2f SNR=%5.2f" % (self.dm, self.snr)
        else:
            result = "  DM=%6.2f SNR=%5.2f Sigma=%5.2f" % \
                        (self.dm, self.snr, self.sigma)
        result += "   " + int(self.snr/3.0)*'*' + '\n'
        return result


class AccelcandsError(Exception):
    """An error to throw when a line in a *.accelcands file
        has an unrecognized format.
    """
    pass


def write_candlist(candlist, fn=sys.stdout):
    """Write candlist provided to a file with filename fn.

        Inputs:
            fn - path of output candlist, or an open file object
                (Default: standard output stream)
        NOTE: if fn is an already-opened file-object it will not be
                closed by this function.
    """
    if type(fn) == bytes:
        toclose = True
        file = open(fn, 'w')
    else:
        # fn is actually a file-object
        toclose = False
        file = fn

    file.write("#" + "file:candnum".center(66) + "DM".center(9) + \
               "SNR".center(8) + "sigma".center(8) + "numharm".center(9) + \
               "ipow".center(9) + "cpow".center(9) +  "P(ms)".center(14) + \
               "r".center(12) + "z".center(8) + "numhits".center(9) + "\n")
    candlist.sort(cmp=lambda x, y: cmp(x.sigma, y.sigma), reverse=True)
    for cand in candlist:
        cand.dmhits.sort(cmp=lambda x, y: cmp(x.dm, y.dm))
        file.write(str(cand))
    if toclose:
        file.close()


def parse_candlist(candlistfn):
    """Parse candidate list and return a list of Candidate objects.
        
        Inputs:
            candlistfn - path of candlist, or an open file object
    
        Outputs:
            list of Candidates objects
    """
    if type(candlistfn) == bytes:
        candlist = open(candlistfn, 'r')
    else:
        # candlistfn is actually a file-object
        candlist = candlistfn
    cands = []
    for line in candlist:
        if not line.partition("#")[0].strip():
            # Ignore lines with no content
            continue
        candinfo_match = candinfo_re.match(line)
        if candinfo_match:
            cdict = candinfo_match.groupdict()
            cdict['period'] = float(cdict['period'])/1000.0 # convert ms to s
            cands.append(Candidate(**cdict))
        else:
            dmhit_match = dmhit_re.match(line)
            if dmhit_match:
                cands[-1].add_dmhit(**dmhit_match.groupdict())
            else:
                raise AccelcandsError("Line has unrecognized format!\n(%s)\n" % line)
    return cands
