"""
RINEX 2 OBS reader
under testing
Michael Hirsch, Greg Starr
MIT License
"""
from __future__ import division
import numpy as np
import matplotlib.pyplot as plt
from itertools import chain
from datetime import datetime, timedelta
from pandas import DataFrame,Panel
from pandas.io.pytables import read_hdf
from os.path import splitext
import sys
if sys.version_info<(3,):
    py3 = False
    from StringIO import StringIO
else:
    from io import BytesIO
    py3 = True

def rinexobs(obsfn,writeh5,maxtimes=None):
    stem,ext = splitext(obsfn)
    if ext[-1].lower() == 'o': #raw text file
        with open(obsfn,'r') as rinex:
            header = readHead(rinex)
            (svnames,types,obstimes,maxsv,obstypes) = makeSvSet(header,maxtimes)
            blocks = makeBlocks(rinex,types,maxsv,svnames,obstypes,obstimes)
    #%% save to disk (optional)
        if writeh5:
            h5fn = stem + '.h5'
            print('saving OBS data to {}'.format(h5fn))
            blocks.to_hdf(h5fn,key='OBS',complevel=6)
    elif ext.lower() == '.h5':
        blocks = read_hdf(obsfn,key='OBS')
        print('loaded OBS data from {} to {}'.format(blocks.items[0],blocks.items[-1]))
    return blocks

def TEC(data,startTime):
    # TODO: update to use datetime()
    for d in data:
        difference = []
        for i in range(6):
            difference.append(d[0][i]-startTime[i])
        time = difference[5]+60*difference[4]+3600*difference[3]+86400*difference[2]
        tec = (9.517)*(10**16)*(d[7]-d[2])
        TECs.append([time,tec])

def readHead(rinex):
    header = []
    while True:
        header.append(rinex.readline())
        if 'END OF HEADER' in header[-1]:
            break

    return header

def makeSvSet(header,maxtimes):
    svnames=[]
#%% get number of obs types
    numberOfTypes = int([l[:6] for l in header if "# / TYPES OF OBSERV" in l[60:]][0])
    obstypes = [l[6:60].split() for l in header if "# / TYPES OF OBSERV" in l[60:]]
    obstypes = list(chain.from_iterable(obstypes))
#%% get number of satellites
    numberOfSv = int([l[:6] for l in header if "# OF SATELLITES" in l[60:]][0])
#%% get observation time extents
    """
    here we take advantage of that there will always be whitespaces--for the data itself
    there aren't always whitespaces between data, so we have to get more explicit.
    Pynex currently takes the explicit indexing by text column instead of split().
    """
    firstObs = _obstime([l[:60] for l in header if "TIME OF FIRST OBS" in l[60:]][0].split(None))
    lastObs  = _obstime([l[:60] for l in header if "TIME OF LAST OBS" in l[60:]][0].split(None))
    interval_sec = float([l[:10] for l in header if "INTERVAL" in l[60:]][0])
    interval_delta = timedelta(seconds=int(interval_sec),
                               microseconds=int(interval_sec % 1)*100000)
    if maxtimes is None:
        ntimes = int(np.ceil((lastObs-firstObs)/interval_delta) + 1)
    else:
        ntimes = maxtimes
    obstimes = firstObs + interval_delta * np.arange(ntimes)
    #%% get satellite numbers
    linespersat = int(np.ceil(numberOfTypes / 9))
    assert linespersat > 0

    satlines = [l[:60] for l in header if "PRN / # OF OBS" in l[60:]]

    for i in range(numberOfSv):
        svnames.append(satlines[linespersat*i][3:6])

    return svnames,numberOfTypes, obstimes, numberOfSv,obstypes

def _obstime(fol):
    year = int(fol[0])
    if 80<= year <=99:
        year+=1900
    elif year<80: #because we might pass in four-digit year
        year+=2000
    return datetime(year=year, month=int(fol[1]), day= int(fol[2]),
                    hour= int(fol[3]), minute=int(fol[4]),
                    second=int(float(fol[5])),
                    microsecond=int(float(fol[5]) % 1) *100000
                    )

def _block2df(block,svnum,obstypes,svnames):
    """
    input: block of text corresponding to one time increment INTERVAL of RINEX file
    output: 2-D array of float64 data from block. Future: consider whether best to use Numpy, Pandas, or Xray.
    """
    if py3:
        strio = BytesIO(block.encode())
    else:
        strio = StringIO(block)
    barr = np.genfromtxt(strio,
                         delimiter=(14,1,1, 14,1,1, 14,1,1, 14,1,1, 14,1,1)).reshape((svnum,-1),
                         order='C'
                         )
    #FIXME: I didn't return the "signal strength" and "lock indicator" columns
    return DataFrame(index=svnames,columns=obstypes, data = barr[:,::3])


def makeBlocks(rinex,ntypes,maxsv,svnames,obstypes,obstimes):
    """
    inputs:
    rinex: file stream
    ntypes: number of observation types
    obstimes: datetime() of each observation
    obstypes: type of measurment e.g. P1, P2,...
    maxsv: maximum number of SVs the reciever saw in this file (i.e. across the entire obs. time)

    outputs:
    blocks: dimensions timeINTERVALs x maxsv x ntypes (page x row x col)
    """
    blocks = Panel(items=obstimes, #FIXME items should be datetime based on start,stop,INTERVAL
                   major_axis=svnames,
                   minor_axis=obstypes)

    i = 0
    while i<= obstimes.size: #this means maxtimes was specified, otherwise we'd reach end of file
        sathead = rinex.readline()
        svnum = int(sathead[29:32])
        blocksize = (svnum*ntypes)//5 # need double-slash for integer result in modern Python
        satnames = sathead[32:68]
        for _ in range(int(np.ceil(svnum/12))-1):
            line = rinex.readline()
            sathead+=line
            satnames+=line[32:68] #FIXME is this right end?
        blocksvnames = grouper(satnames,3)
#%% read this INTERVAL's text block
        block = ''.join(rinex.readline() for _ in range(blocksize))
        btime = _obstime(sathead[:26].split()) #FIXME use this to index panel
        bdf = _block2df(block,svnum,obstypes,blocksvnames)
        #FIXME index by time, not "i"
        blocks.loc[btime,blocksvnames] = bdf
        i+=1

    return blocks

def grouper(txt,n):
    return [txt[n*i:n+n*i] for i in range(len(txt)//n)]

if __name__ == '__main__':
    from argparse import ArgumentParser
    p = ArgumentParser('our program to read RINEX 2 OBS files')
    p.add_argument('obsfn',help='RINEX 2 obs file',type=str,nargs='?',default='log00410.15o')
    p.add_argument('--h5',help='write observation data for faster loading',action='store_true')
    p.add_argument('--maxtimes',help='Choose to read only the first N INTERVALs of OBS file',type=int,default=None)
    p.add_argument('--profile',help='profile code for debugging',action='store_true')
    p = p.parse_args()

    if p.profile:
        import cProfile
        from pstats import Stats
        profFN = 'RinexObsReader.pstats'
        cProfile.run('rinexobs(p.obsfn,p.h5,p.maxtimes)',profFN)
        Stats(profFN).sort_stats('time','cumulative').print_stats(20)
    else:
        blocks = rinexobs(p.obsfn,p.h5,p.maxtimes)
#%% plot
        plt.plot(blocks.items,blocks.ix[:,'G 1','P1'])

        plt.show()
#%% TEC can be made another column (on the minor_axis) of the blocks Panel.