"""
datfile.py

PRESTO .dat file object.

Patrick Lazarus, June 16, 2009
"""

import os.path

import numpy as np
import scipy.interpolate as interp

import psr_utils
import infodata
from . import pulse

# Define constants and default values
DTYPE = 'float32'       # binary data in PRESTO's .dat files
# is stored as 32-bit floats


class Datfile:
    def __init__(self, datfn, dtype=DTYPE):
        self.datfn = datfn
        self.dtype = np.dtype(dtype)
        self.bytes_per_sample = self.dtype.itemsize
        if self.datfn.endswith(".dat"):
            self.basefn = self.datfn[:-4]
            self.datfile = open(datfn, 'r')
            self.inffn = "%s.inf" % self.basefn
            self.infdata = infodata.infodata(self.inffn)
            self.inf = self.infdata
            # Corrections need to be applied to data from .inf file
            correct_infdata(self.infdata)
        else:
            raise "Filename (%s) doesn't end with '.dat'"
        # initialize file, and current sample, time, and MJD counters
        self.rewind()

    def close(self):
        """Close .dat file.
        """
        self.datfile.close()

    def __str__(self):
        string_repr = "%s:\n" % self.origfn
        string_repr += "\tCurrent sample: %d\n" % self.currsample
        if hasattr(self.infdata, 'epoch'):
            string_repr += "\tCurrent desired MJD: %0.15f\n" % self.currmjd_desired
            string_repr += "\tCurrent actual MJD: %0.15f\n" % self.currmjd_actual
        string_repr += "\tCurrent desired time: %0.9f\n" % self.currtime_desired
        string_repr += "\tCurrent actual time: %0.9" % self.currtime_actual
        return string_repr

    def __read(self, N):
        """Private method:
            Read N samples from dat file and return numpy array
            of the data.
            Only return data if at least N samples remain in
            the data file. Otherwise return None.
        """
        new_curr_sample = self.currsample + N
        if new_curr_sample > self.infdata.N:
            return None
        else:
            self.currsample = new_curr_sample
            if hasattr(self.infdata, 'epoch'):
                self.currmjd_actual += self.infdata.dt * N / \
                    float(psr_utils.SECPERDAY)
            self.currtime_actual += self.infdata.dt * N
            return np.fromfile(self.datfile, dtype=self.dtype, count=N)

    def __seek(self, N):
        self.datfile.seek(N*self.bytes_per_sample)
        self.currsample = N
        if hasattr(self.infdata, 'epoch'):
            self.currmjd_actual = self.infdata.dt * N / \
                float(psr_utils.SECPERDAY)
        self.currtime_actual = self.infdata.dt * N

    def __update_desired_time(self, T):
        """Private method:
            Update current desired time and MJD
        """
        self.currtime_desired += T
        if hasattr(self.infdata, 'epoch'):
            self.currmjd_desired += T / float(psr_utils.SECPERDAY)

    def read_to(self, N):
        """Read until sample N from current sample.

            Input:
                N: Sample to read to (if N==-1, read to the end of the file.)

            Output:
                data: data from current sample up to N.
        """
        if N == -1:
            numtoread = self.inf.N - self.currsample
        else:
            numtoread = N - self.currsample
        return self.read_Nsamples(numtoread)

    def get_baseline_spline(self, span=1.0):
        """Get spline representation of baseline.
            Split time series into blocks and calculate the median of
            each block. interpolate between median values using
            a spline.

            Input:
                span: The time span for blocks, in seconds (Default: 1s)

            Output:
                spline: The spline object representing the baseline.
        """
        self.rewind()

        istart = 0
        block = self.read_Tseconds(span)
        xx = []
        meds = []
        while block is not None:
            iend = istart + len(block)
            xx.append(0.5*(istart+iend))
            meds.append(np.median(block))
            istart = iend
            block = self.read_Tseconds(span)

        spline = interp.InterpolatedUnivariateSpline(xx, meds, bbox=(0, iend))
        return spline

    def write_debaselined(self, span=1.0):
        """Write time series with baseline removed.

            Input:
                span: The time span for blocks, in seconds (Default: 1s)

            Output:
                outfn: The name of the output file.
        """
        outbase = "%s.debasline" % self.basefn
        spline = self.get_baseline_spline(span)
        self.rewind()
        data = self.read_all()
        nout = len(data)-span/2.0/self.inf.dt
        data = data[:nout]
        xs = np.arange(nout)
        baseline = spline(xs)
        (data-baseline).tofile(outbase+".dat")

        # Create inf file.
        with open(self.inffn, 'r') as inffile, open(outbase+".inf", 'w') as outfile:
            for line in inffile:
                if not line.strip():
                    continue
                if line.startswith(" Data file name"):
                    outfile.write(
                        " Data file name without suffix          =  %s\n" % outbase)
                elif line.startswith(" Number of bins "):
                    outfile.write(
                        " Number of bins in the time series      =  %d\n" % nout)
                else:
                    outfile.write(line)
            outfile.write(
                "    Baseline was removed with 'datafile.py' (by Patrick Lazarus) using a block duration of %g s\n" % span)

        return outbase+'.dat'

    def read_Nsamples(self, N):
        """Read N samples from datfile and return a numpy array
            of the data, or None if there aren't N samples of
            data left in the file.
        """
        # Read data
        data = self.__read(N)
        if data is not None:
            self.__update_desired_time(N * self.infdata.dt)
        return data

    def seek_to(self, T):
        self.rewind()
        # Compute number of samples to read
        endsample = np.round((self.currtime_desired+T)/self.infdata.dt)
        sample_num = int(endsample-self.currsample)
        self.__seek(sample_num)
        self.currtime_desired = T
        if hasattr(self.infdata, 'epoch'):
            self.currmjd_desired = self.infdata.epoch + \
                T / float(psr_utils.SECPERDAY)
        return sample_num

    def read_Tseconds(self, T):
        """Read T seconds worth of data from datfile and return
            a numpy array of the data, or None if there aren't
            T seconds worth of data left in the file.
        """
        # Compute number of samples to read
        endsample = np.round((self.currtime_desired+T)/self.infdata.dt)
        num_samples_to_read = int(endsample-self.currsample)
        # Read data
        data = self.__read(num_samples_to_read)
        if data is not None:
            self.__update_desired_time(T)
        return data

    def read_all(self):
        """Read all samples in datfile and return a numpy array of the data.
            File is rewound before reading.
        """
        self.rewind()
        return self.__read(self.infdata.N)

    def rewind(self):
        """Rewind file to beginning. Also, reset current time,
           current mjd and current sample.
        """
        self.datfile.seek(0)
        # Current sample (number of samples already read)
        self.currsample = 0
        # Actual current time (incrememted by integer number of samples)
        self.currtime_actual = 0.0
        # Desired current time (keep track of requests given in seconds)
        self.currtime_desired = 0.0
        if hasattr(self.infdata, 'epoch'):
            # Actual current MJD (incremented by integer number of samples)
            self.currmjd_actual = self.infdata.epoch
            # Desired current MJD (keep track of requests)
            self.currmjd_desired = self.infdata.epoch

    def pulses(self, period_at_mjd, time_to_skip=0.0):
        """Generator method to generate/iterate over pulse
            profiles from datfile.
            'period_at_mjd' is a function that, given a mjd,
            will return the spin period at that mjd.
            Skip 'time_to_skip' seconds at the start of the
            observation. (First pulse period after skip is
            still called pulse #1)
        """
        if not hasattr(self.infdata, 'epoch'):
            raise NotImplementedError(
                "Cannot use 'pulses(...)' if there is no MJD in inf file")
        # Initialize
        self.rewind()
        if time_to_skip > 0.0:
            print("Burning %f s at start of obs." % time_to_skip)
            self.read_Tseconds(time_to_skip)

        pulse_number = 1
        # Copy current mjd and time since reading data
        # will modify the object attributes
        current_time = self.currtime_actual
        current_mjd = self.currmjd_actual
        #
        # NOTE: Using currmjd_actual, is this correct?
        #       Should we be using currmjd_desired instead?
        #
        current_period = period_at_mjd(current_mjd)
        current_pulse = self.read_Tseconds(current_period)
        while current_pulse is not None:
            # yield (return) current pulse (and other information)
            yield pulse.Pulse(number=pulse_number, mjd=current_mjd,
                              time=current_time, duration=current_period,
                              profile=current_pulse, origfn=self.datfn,
                              dt=self.infdata.dt, dm=self.infdata.DM,
                              telescope=self.infdata.telescope,
                              lofreq=self.infdata.lofreq,
                              chan_width=self.infdata.chan_width,
                              bw=self.infdata.BW)
            # Update pulse number, mjd, period and pulse
            pulse_number += 1
            current_time = self.currtime_actual
            current_mjd = self.currmjd_actual
            current_period = period_at_mjd(current_mjd)
            current_pulse = self.read_Tseconds(current_period)


def correct_infdata(inf):
    """Only argument is an infodata object. The infodata object
        is corrected in place (nothing is returned).

        The following is an emperical correction for SPIGOT
        data. The comment and code are taken from Scott Ransom's
        PRESTO's prepfold.py

        The following "fixes" (we think) the observing frequency of the Spigot
        based on tests done by Ingrid on 0737 (comparing it to GASP)
        The same sorts of corrections should be made to WAPP data as well...
        The tepoch corrections are empirically determined timing corrections
        Note that epoch is only double precision and so the floating
        point accuracy is ~1 us!
    """
    if inf.telescope == 'GBT':
        if np.fabs(np.fmod(inf.dt, 8.192e-05) < 1e-12) and \
           ("spigot" in inf.instrument.lower() or
                "guppi" not in inf.instrument.lower()):
            if inf.chan_width == 800.0/1024:  # Spigot 800 MHz mode 2
                inf.lofreq -= 0.5 * inf.chan_width
                # original values
                #if inf.epoch > 0.0: inf.epoch += 0.039334/86400.0
                # values measured with 1713+0747 wrt BCPM2 on 13 Sept 2007
                if inf.epoch > 0.0:
                    inf.epoch += 0.039365/86400.0
            elif inf.chan_width == 800.0/2048:
                inf.lofreq -= 0.5 * inf.chan_width
                if inf.epoch < 53700.0:  # Spigot 800 MHz mode 16 (downsampled)
                    if inf.epoch > 0.0:
                        inf.tepoch += 0.039352/86400.0
                else:  # Spigot 800 MHz mode 14
                    # values measured with 1713+0747 wrt BCPM2 on 13 Sept 2007
                    if inf.epoch > 0.0:
                        inf.epoch += 0.039365/86400.0
            elif inf.chan_width == 50.0/1024 or inf.chan_width == 50.0/2048:  # Spigot 50 MHz modes
                inf.lofreq += 0.5 * inf.chan_width
                # Note: the offset has _not_ been measured for the 2048-lag mode
                if inf.epoch > 0.0:
                    inf.epoch += 0.039450/86400.0
