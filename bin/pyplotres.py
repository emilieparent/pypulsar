#!/usr/bin/env python

# A simple command line version of plotres written in python
# using matplotlib and numpy
#
#           Patrick Lazarus, Feb 26th, 2009

import optparse
import sys
import re
import os
import os.path
import types
import shutil
import tempfile
import warnings
import subprocess

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

import binary_psr
import parfile as par
import residuals

from pypulsar.utils.astro import calendar

# Available x-axis types
xvals = ['mjd', 'year', 'numtoa', 'orbitphase']
xind = 0
# Available y-axis types
yvals = ['phase', 'usec', 'sec']
yind = 0


def get_resids():
    """Read residuals using 'residuals.py' and return them.
    """
    # Need to check if on 32-bit or 64-bit computer
    # (the following is a hack to find out if we're on a borg or borgii node)
    if os.uname()[4] == 'i686':
        # 32-bit computer
        r = residuals.read_residuals()
    else:
        # 64-bit computer
        # r = residuals.read_residuals_64bit()
        r = residuals.read_residuals()
    return r


class TempoError(Exception):
    """Error to throw when TEMPO returns with a non-zero error code.
    """
    pass


class TempoResults:
    def __init__(self, freqbands=[[0, 'inf']]):
        """Read TEMPO results (resid2.tmp, tempo.lis, timfile and parfiles)
            freqbands is a list of frequency pairs to display.
        """
        # Open tempo.lis. Parse it and find input .tim and .par files. Also find output .par file.
        inputfiles_re = re.compile(
            r"Input data from (.*\.tim.*),  Parameters from (.*\.par.*)")
        outputfile_re = re.compile(r"Assumed parameters -- PSR (.*)$")
        tempolisfile = open("tempo.lis")
        intimfn, inparfn, outparfn = None, None, None
        for line in tempolisfile:
            match = inputfiles_re.search(line)
            if match:
                intimfn = match.group(1).strip()
                inparfn = match.group(2).strip()
            else:
                match = outputfile_re.search(line)
                if match:
                    outparfn = "%s.par" % match.group(1).strip()
            if (intimfn != None) and (inparfn != None) and (outparfn != None):
                # Found what we're looking for no need to continue parsing the file
                break
        tempolisfile.close()

        # Record filename
        self.inparfn = inparfn
        self.outparfn = outparfn
        self.intimfn = intimfn

        # Read parfiles
        self.inpar = par.psr_par(inparfn)
        self.outpar = par.psr_par(outparfn)

        # Read residuals
        r = get_resids()

        self.max_TOA = r.bary_TOA.max()
        self.min_TOA = r.bary_TOA.min()

        self.freqbands = freqbands
        self.residuals = {}
        for lo, hi in self.freqbands:
            indices = (r.bary_freq >= lo) & (r.bary_freq < hi)
            self.residuals[get_freq_label(lo, hi)] = \
                Resids(r.bary_TOA[indices], r.bary_freq[indices],
                       np.arange(r.numTOAs)[indices], r.orbit_phs[indices],
                       r.postfit_phs[indices], r.postfit_sec[indices],
                       r.prefit_phs[indices], r.prefit_sec[indices],
                       r.uncertainty[indices], r.weight[indices],
                       self.inpar, self.outpar)

    def get_info(self, freq_label, index, postfit=True):
        """Given a freq_label and index return formatted text
            describing the TOA residual.

            Assume postfit period for calculating residual in phase, 
            unless otherwise indicated.
        """
        r = self.residuals[freq_label]
        description = []
        description.append("TOA Selected:")
        description.append("\tNumber: %s" % r.TOA_index[index][0])
        description.append("\tEpoch (MJD): %s" % r.bary_TOA[index][0])
        if yvals[yind] == "phase":
            description.append("\tPre-fit residual (phase): %s" %
                               r.prefit_phs[index][0])
            description.append("\tPost-fit residual (phase): %s" %
                               r.postfit_phs[index][0])
            if postfit:
                description.append("\tUncertainty (phase): %s" %
                                   (r.uncertainty[index][0]/r.outpar.P0))
            else:
                description.append("\tUncertainty (phase): %s" %
                                   (r.uncertainty[index][0]/r.inpar.P0))
        elif yvals[yind] == "usec":
            description.append("\tPre-fit residual (usec): %s" %
                               (r.prefit_sec[index][0]*1e6))
            description.append("\tPost-fit residual (usec): %s" %
                               (r.postfit_sec[index][0]*1e6))
            description.append("\tUncertainty (usec): %s" %
                               (r.uncertainty[index][0]*1e6))
        elif yvals[yind] == "sec":
            description.append("\tPre-fit residual (sec): %s" %
                               r.prefit_sec[index][0])
            description.append("\tPost-fit residual (sec): %s" %
                               r.postfit_sec[index][0])
            description.append("\tUncertainty (sec): %s" %
                               r.uncertainty[index][0])
        description.append("\tFrequency (MHz): %s" % r.bary_freq[index][0])
        return description

    def get_postfit_model(self, startmjd, endmjd, numpts=1000):
        """Return the postfit model that was subtracted from
            the prefit redisuals for the MJD range provided.

            Inputs:
                startmjd: The starting MJD.
                endmjd: The ending MJD.
                numpts: The number of points to use.
                    (Default: 1000)

            Outputs:
                mjds: The MJDs corresponding to the model.
                model: A numpy array with redsiduals representing the
                    model that was subtracted from the prefit residuals
                    to get the postfit residual.
        """
        # Establish a list of MJDs to determin the model at
        mjds = np.linspace(startmjd, endmjd, numpts)

        # Get phase and freq for each MJD with the postfit ephem
        postfit_polycos = mypolycos.create_polycos(self.outpar,
                                                   '3', 1410, startmjd, endmjd)

        phases = np.empty(numpts)
        freqs = np.empty(numpts)
        for ii, mjd in enumerate(mjds):
            mjdi = int(mjd)
            mjdf = mjd % 1
            phs, freq = postfit_polycos.get_phs_and_freq(mjdi, mjdf)
            phases[ii] = phs
            freqs[ii] = freq

        # Round MJDs to nearest integer rotations
        phases -= 1*(phases > 0.5)
        mjds -= phases/freqs/psr_utils.SECPERDAY

        # Input MJDs into prefit ephem to find resids in phase
        prefit_polycos = mypolycos.create_polycos(self.inpar,
                                                  '3', 1410, startmjd, endmjd)
        model = np.empty(numpts)
        for ii, mjd in enumerate(mjds):
            mjdi = int(mjd)
            mjdf = mjd % 1
            model = prefit_polycos.get_phase(mjdi, mjdf)
        model -= 1*(model > 0.5)

        return mjds, model


class Resids:
    """The Resids object contains the following information
        about TEMPO residuals:
            bary_TOA
            bary_freq
            numTOAs
            orbit_phs
            postfit_phs
            postfit_sec
            prefit_phs
            prefit_sec
            uncertainty
            weight
    """

    def __init__(self, bary_TOA, bary_freq, TOA_index, orbit_phs,
                 postfit_phs, postfit_sec, prefit_phs, prefit_sec,
                 uncertainty, weight, inpar, outpar):
        self.bary_TOA = bary_TOA
        self.bary_freq = bary_freq
        self.TOA_index = TOA_index
        self.orbit_phs = orbit_phs
        self.postfit_phs = postfit_phs
        self.postfit_sec = postfit_sec
        self.prefit_phs = prefit_phs
        self.prefit_sec = prefit_sec
        self.uncertainty = uncertainty
        self.weight = weight
        self.inpar = inpar
        self.outpar = outpar

    def get_xdata(self, key):
        """Return label describing xaxis and the corresponding 
            data given keyword 'key'.
        """
        if not isinstance(key, bytes):
            raise ValueError("key must be of type string.")
        xopt = key.lower()
        if xopt == 'numtoa':
            xdata = self.TOA_index
            xlabel = "TOA Number"
        elif xopt == 'mjd':
            xdata = self.bary_TOA
            xlabel = "MJD"
        elif xopt == 'orbitphase':
            xdata = self.orbit_phs
            xlabel = "Orbital Phase"
        elif xopt == 'year':
            xdata = calendar.MJD_to_year(self.bary_TOA)
            xlabel = "Year"
        else:
            raise ValueError("Unknown xaxis type (%s)." % xopt)
        return (xlabel, xdata)

    def get_ydata(self, key, postfit=True):
        """Return label describing yaxis and the corresponding 
            data/errors given keyword 'key'.
            'postfit' is a boolean argument that determines if
            postfit, or prefit data is to be returned.
        """
        if not isinstance(key, bytes):
            raise ValueError("key must be of type string.")
        yopt = key.lower()
        if postfit:
            if yopt == 'phase':
                ydata = self.postfit_phs
                #
                # NOTE: Should use P at TOA not at PEPOCH
                #
                yerror = self.uncertainty/self.outpar.P0
                ylabel = "Residuals (Phase)"
            elif yopt == 'usec':
                ydata = self.postfit_sec*1e6
                yerror = self.uncertainty*1e6
                ylabel = r"Residuals ($\mu$s)"
            elif yopt == 'sec':
                ydata = self.postfit_sec
                yerror = self.uncertainty
                ylabel = "Residuals (Seconds)"
            else:
                raise ValueError("Unknown yaxis type (%s)." % yopt)
        else:
            if yopt == 'phase':
                ydata = self.prefit_phs
                #
                # NOTE: Should use P at TOA not at PEPOCH
                #
                yerror = self.uncertainty/self.inpar.P0
                ylabel = "Residuals (Phase)"
            elif yopt == 'usec':
                ydata = self.prefit_sec*1e6
                yerror = self.uncertainty*1e6
                ylabel = "Residuals (uSeconds)"
            elif yopt == 'sec':
                ydata = self.prefit_sec
                yerror = self.uncertainty
                ylabel = "Residuals (Seconds)"
            else:
                raise ValueError("Unknown yaxis type (%s)." % yopt)
        return (ylabel, ydata, yerror)


def plot_data(tempo_results, xkey, ykey, postfit=True, prefit=False,
              interactive=True, mark_peri=False, show_legend=True):
    # figure out what should be plotted
    # True means to plot postfit
    # False means to plot prefit
    if postfit and prefit:
        to_plot_postfit = [False, True]
    elif postfit and not prefit:
        to_plot_postfit = [True]
    elif not postfit and prefit:
        to_plot_postfit = [False]
    else:
        raise EmptyPlotValueError(
            "At least one of prefit and postfit must be True.")
    subplot = 1
    numsubplots = len(to_plot_postfit)
    global axes
    axes = []
    handles = []
    labels = []
    for usepostfit in to_plot_postfit:
        TOAcount = 0
        # All subplots are in a single column
        if subplot == 1:
            axes.append(plt.subplot(numsubplots, 1, subplot))
        else:
            axes.append(plt.subplot(numsubplots, 1, subplot, sharex=axes[0]))

        # set tick formatter to not use scientific notation or an offset
        tick_formatter = matplotlib.ticker.ScalarFormatter(useOffset=False)
        tick_formatter.set_scientific(False)
        axes[-1].xaxis.set_major_formatter(tick_formatter)

        for lo, hi in tempo_results.freqbands:
            freq_label = get_freq_label(lo, hi)
            resids = tempo_results.residuals[freq_label]
            xlabel, xdata = resids.get_xdata(xkey)
            ylabel, ydata, yerr = resids.get_ydata(ykey, usepostfit)
            if not usepostfit and xkey == 'mjd' and ykey == 'phase':
                mjds, model = tempo_results.get_postfit_model(min(xdata),
                                                              max(xdata))
                plt.plot(mjds, model, 'k:', lw=0.25)

            if len(xdata):
                # Plot the residuals
                handle = plt.errorbar(xdata, ydata, yerr=yerr, fmt='.',
                                      label=freq_label, picker=5)
                if subplot == 1:
                    handles.append(handle[0])
                    labels.append(freq_label)
                TOAcount += xdata.size
        # Finish off the plot
        plt.axhline(0, ls='--', label="_nolegend_", c='k', lw=0.5)
        axes[-1].ticklabel_format(style='plain', axis='x')

        if mark_peri and hasattr(tempo_results.outpar, 'BINARY'):
            # Be sure to check if pulsar is in a binary
            # Cannot mark passage of periastron if not a binary
            if usepostfit:
                binpsr = binary_psr.binary_psr(tempo_results.outpar.FILE)
            else:
                binpsr = binary_psr.binary_psr(tempo_results.inpar.FILE)
            xmin, xmax = plt.xlim()
            mjd_min = tempo_results.min_TOA
            mjd_max = tempo_results.max_TOA
            guess_mjds = np.arange(mjd_max + binpsr.par.PB,
                                   mjd_min - binpsr.par.PB, -binpsr.par.PB)
            for mjd in guess_mjds:
                peri_mjd = binpsr.most_recent_peri(float(mjd))
                if xkey == 'mjd':
                    plt.axvline(peri_mjd, ls=':',
                                label='_nolegend_', c='k', lw=0.5)
                elif xkey == 'year':
                    print("plotting peri passage")
                    plt.axvline(calendar.MJD_to_year(peri_mjd),
                                ls=':', label='_nolegend_', c='k', lw=0.5)
            plt.xlim((xmin, xmax))
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        # plt.tick_params(labelsize='small')
        if interactive:
            if usepostfit:
                plt.title("Postfit Redisuals (Number of TOAs: %d)" % TOAcount)
            else:
                plt.title("Prefit Redisuals (Number of TOAs: %d)" % TOAcount)
        subplot += 1

    if numsubplots > 1:
        # Increase spacing between subplots.
        plt.subplots_adjust(hspace=0.25)

    # Write name of input files used for timing on figure
    if interactive:
        fntext = "TOA file: %s, Parameter file: %s" % \
            (tempo_results.intimfn, tempo_results.inparfn)
        figure_text = plt.figtext(0.01, 0.01, fntext, verticalalignment='bottom',
                                  horizontalalignment='left')

    # Make the legend and set its visibility state
    leg = plt.figlegend(handles, labels, 'upper right', prop={"size": 8})
    leg.set_visible(show_legend)
    leg.legendPatch.set_alpha(0.5)


def create_plot():
    # Set up the plot
    fig = plt.figure(figsize=(11, 8.5))
    fig.canvas.set_window_title("PyPlotres")


def get_freq_label(lo, hi):
    """Return frequency label given a lo and hi
        frequency pair.
    """
    if np.isposinf(hi):
        hi = r'$\infty$'
    return "%s - %s MHz" % (lo, hi)


def savefigure(savefn='./resid2.tmp.ps'):
    print("Saving plot to %s" % savefn)
    plt.savefig(savefn, orientation='landscape', papertype='letter')


def reloadplot():
    # Reload residuals and replot
    print("Plotting...")
    fig = plt.gcf()
    fig.set_visible(False)
    plt.clf()  # clear figure
    tempo_results = TempoResults(options.freqbands)
    try:
        plot_data(tempo_results, options.xaxis, options.yaxis,
                  postfit=options.postfit, prefit=options.prefit,
                  interactive=options.interactive,
                  mark_peri=options.mark_peri, show_legend=options.legend)
    except EmptyPlotValueError as msg:
        print(msg)
        print("Press 'p'/'P' to add prefit/postfit plot.")
        plt.figtext(0.5, 0.5, (str(msg) + "\n" +
                               "Press 'p'/'P' to add prefit/postfit plot."),
                    horizontalalignment='center',
                    verticalalignment='center',
                    bbox=dict(facecolor='white', alpha=0.75))
    fig.set_visible(True)
    redrawplot()


def redrawplot():
    plt.draw()


def quit():
    print("Quiting...")
    sys.exit(0)


def pick(event):
    global tempo_results
    index = event.ind
    axes = event.mouseevent.inaxes
    if axes:
        title = axes.get_title()
        postfit = ("Postfit" in title)
    if len(index) == 1:
        freq_label = event.artist.get_label()
        info = tempo_results.get_info(freq_label, index, postfit)
        print_text(info)
    else:
        print("Multiple TOAs selected. Zoom in and try again.")


def print_text(lines, *args, **kwargs):
    """Print lines of text (in a list) in the terminal."""
    print('\n'.join(lines))


def print_help():
    # Display help
    print("Helping...")
    print("-"*80)
    print("Help - Hotkeys definitions:")
    print("\th - Display this help")
    print("\tq - Quit")
    print("\ts - Save current plot(s) to PostScript file")
    print("\tp - Toggle prefit display on/off")
    print("\tP - Toggle postfit display on/off")
    print("\tz - Toggle Zoom-mode on/off")
    print("\tL - Toggle legend on/off")
    print("\to - Go to original view")
    print("\t< - Go to previous view")
    print("\t> - Go to next view")
    print("\tx - Set x-axis limits (terminal input required)")
    print("\ty - Sey y-axis limits (terminal input required)")
    print("\tr - Reload residuals")
    print("\tt - Cycle through y-axis types ('phase', 'usec', 'sec')")
    print(
        "\t[Space] - Cycle through x-axis types ('MJD', 'year', 'numTOA', 'orbitphase')")
    print("\t[Left mouse] - Select TOA (display info in terminal)")
    print("\t             - Select zoom region (if Zoom-mode is on)")
    print("-"*80)


def keypress(event):
    global tempo_results
    global options
    global xind, xvals
    global yind, yvals
    if type(event.key) == bytes:
        if event.key.lower() == 'q':
            quit()
        elif event.key.lower() == 's':
            savefigure()
        elif event.key.lower() == 'r':
            reloadplot()
        elif event.key.upper() == 'L':
            leg = plt.gcf().legends[0]
            options.legend = not options.legend
            leg.set_visible(options.legend)
            redrawplot()
        elif event.key.lower() == 'z':
            # Turn on zoom mode
            print("Toggling zoom mode...")
            event.canvas.toolbar.zoom()
        elif event.key.lower() == 'o':
            # Restore plot to original view
            print("Restoring plot...")
            event.canvas.toolbar.home()
        elif event.key.lower() == ',' or event.key.lower() == '<':
            # Go back to previous plot view
            print("Going back...")
            event.canvas.toolbar.back()
        elif event.key.lower() == '.' or event.key.lower() == '>':
            # Go forward to next plot view
            print("Going forward...")
            event.canvas.toolbar.forward()
        elif event.key.lower() == ' ':
            xind = (xind + 1) % len(xvals)
            print("Toggling plot type...[%s]" % xvals[xind], xind)
            options.xaxis = xvals[xind]
            reloadplot()
        elif event.key.lower() == 't':
            yind = (yind + 1) % len(yvals)
            print("Toggling plot scale...[%s]" % yvals[yind], yind)
            options.yaxis = yvals[yind]
            reloadplot()
        elif event.key == 'p':
            options.prefit = not options.prefit
            print("Toggling prefit-residuals display to: %s" %
                  ((options.prefit and "ON") or "OFF"))
            reloadplot()
        elif event.key == 'P':
            options.postfit = not options.postfit
            print("Toggling postfit-residuals display to: %s" %
                  ((options.postfit and "ON") or "OFF"))
            reloadplot()
        elif event.key.lower() == 'x':
            # Set x-axis limits
            print("Setting x-axis limits. User input required...")
            xmin = input("X-axis minimum: ")
            xmax = input("X-axis maximum: ")
            try:
                xmin = float(xmin)
                xmax = float(xmax)
                if xmax <= xmin:
                    raise ValueError
            except ValueError:
                print("Bad values provided!")
                return
            plt.xlim(xmin, xmax)
        elif event.key.lower() == 'y':
            global axes
            # Set y-axis limits
            print("Setting y-axis limits. User input required...")
            if len(axes) == 2:
                axes_to_adjust = input("Axes to adjust (pre/post): ")
                if axes_to_adjust.lower().startswith('pre'):
                    plt.axes(axes[0])
                elif axes_to_adjust.lower().startswith('post'):
                    plt.axes(axes[1])
                else:
                    raise ValueError
            ymin = input("Y-axis minimum: ")
            ymax = input("Y-axis maximum: ")
            try:
                ymin = float(ymin)
                ymax = float(ymax)
                if ymax <= ymin:
                    raise ValueError
            except ValueError:
                print("Bad values provided!")
                return
            plt.ylim(ymin, ymax)
        elif event.key.lower() == 'h':
            print_help()


def parse_options():
    (options, sys.argv) = parser.parse_args()
    if sys.argv == []:
        sys.argv = ['pyplotres.py']
    if not options.freqs:
        # Default frequency bands
        freqbands = [['0', '400'],
                     ['400', '600'],
                     ['600', '1000'],
                     ['1000', '1600'],
                     ['1600', '2400'],
                     ['2400', 'inf']]
        #freqbands = [['0', 'inf']]
    else:
        freqbands = []
        for fopt in options.freqs:
            f = fopt.split(':')
            if f[0] == '':
                f[0] = '0'
            if f[-1] == '':
                f[-1] = 'inf'
            if len(f) > 2:
                for i in range(0, len(f)-1):
                    freqbands.append(f[i:i+2])
            else:
                freqbands.append(f)
    freqbands = np.array(freqbands).astype(float)
    freqbands[freqbands.argsort(axis=0).transpose()[0]]
    if np.any(freqbands.flat != sorted(freqbands.flat)):
        raise ValueError("Frequency bands have overlaps or are inverted.")
    options.freqbands = freqbands

    options.mark_peri = False

    if not options.prefit and not options.postfit:
        # If neither prefit or postfit are selected
        # show postfit
        options.postfit = True

    if options.xaxis.lower() not in xvals:
        raise BadOptionValueError("Option to -x/--x-axis (%s) is not permitted." %
                                  options.xaxis)
    if options.yaxis.lower() not in yvals:
        raise BadOptionValueError("Option to -y/--y-axis (%s) is not permitted." %
                                  options.yaxis)
    return options


def main():
    global tempo_results
    global options
    options = parse_options()
    tempo_results = TempoResults(options.freqbands)
    create_plot()
    reloadplot()

    if options.interactive:
        fig = plt.gcf()  # current figure

        # Before setting up our own event handlers delete matplotlib's
        # default 'key_press_event' handler.
        defcids = list(
            fig.canvas.callbacks.callbacks['key_press_event'].keys())
        for cid in defcids:
            fig.canvas.callbacks.disconnect(cid)

        # Now, register our event callback functions
        cid_keypress = fig.canvas.mpl_connect('key_press_event', keypress)
        cid_pick = fig.canvas.mpl_connect('pick_event', pick)

        # Finally, let the show begin!
        plt.ion()
        plt.show()
    else:
        # Save figure and quit
        savefigure()
        quit()


class BadOptionValueError(ValueError):
    """Bad value passed to option parser.
    """
    pass


class EmptyPlotValueError(ValueError):
    """Empty plot.
    """
    pass


if __name__ == '__main__':
    parser = optparse.OptionParser(prog="pyplotres.py",
                                   version="v1.2 Patrick Lazarus (Mar. 29, 2010)")
    parser.add_option('-f', '--freq', dest='freqs', action='append',
                      help="Band of frequencies, in MHz, to be plotted "
                      "(format xxx:yyy). Each band will have a "
                      " different colour. Multiple -f/--freq options "
                      " are allowed. (Default: Plot all frequencies "
                      "in single colour.)",
                      default=[])
    parser.add_option('-x', '--x-axis', dest='xaxis', type='string',
                      help="Values to plot on x-axis. Must be one of "
                      "%s. (Default: '%s')" % (str(xvals), xvals[xind]),
                      default=xvals[xind])
    parser.add_option('-y', '--y-axis', dest='yaxis', type='string',
                      help="Values to plot on y-axis. Must be one of "
                      "%s. (Default: '%s')" % (str(yvals), yvals[yind]),
                      default=yvals[yind])
    parser.add_option('--post', dest='postfit', action='store_true',
                      help="Show postfit residuals. (Default: Don't show "
                      "postfit.)",
                      default=False)
    parser.add_option('--pre', dest='prefit', action='store_true',
                      help="Show prefit residuals. (Default: Don't show "
                      "prefit.)",
                      default=False)
    parser.add_option('-l', '--legend', dest='legend', action='store_true',
                      help="Show legend of frequencies. (Default: Do not "
                      "show legend.)",
                      default=False)
    parser.add_option('--mark-peri', dest='mark_peri', action='store_true',
                      help="Mark passage of periastron. (Default: don't "
                      "mark periastron.)",
                      default=False)
    parser.add_option('--non-interactive', dest='interactive',
                      action='store_false', default=True,
                      help="Save figure and exit. (Default: Show plot, "
                             "only save if requested.)")
    main()
