# These defs are from `automaid` for location parsing and conversion reference.
# Not intended to be used as src in this repo.

def get_gps_from_mer_environment(mer_environment_name, mer_environment):

    '''

        Collect GPS fixes from MER environments within an inclusive datetime range

    '''
    gps_out = []

    # Mermaid environment can be empty
    if mer_environment is None:
        return gps_out

    # Get gps information in the mermaid environment
    gps_mer_list = mer_environment.split("</ENVIRONMENT>")[0].split("<GPSINFO")[1:]
    for gps_mer in gps_mer_list:
        rawstr_dict = {'fixdate': None, 'latitude': None, 'longitude': None, 'clockdrift': None}
        # .MER times are given simply as, e.g., "2020-10-20T02:36:55"
        fixdate = re.findall(r" DATE=(\d+-\d+-\d+T\d+:\d+:\d+)", gps_mer)
        if len(fixdate) > 0:
            fixdate = fixdate[0]
            rawstr_dict['fixdate'] = fixdate
            fixdate = UTCDateTime(fixdate)
        else:
            fixdate = None

        # .MER latitudes are given as, e.g., "-2233.9800" (degrees decimal minutes) where the first 3
        # chars are the degrees (= S22deg33.9800mn) in .LOG parlance, with extra precision here
        latitude = re.findall(r" LAT=([+,-])(\d{2})(\d+\.\d+)", gps_mer)
        if len(latitude) > 0:
            rawstr_dict['latitude'] = re.search("LAT=(.*) LON", gps_mer).group(1)
            latitude = latitude[0]
            if latitude[0] == "+":
                sign = 1
            elif latitude[0] == "-":
                sign = -1
            latitude = sign*(float(latitude[1]) + float(latitude[2])/60.)
        else:
            latitude = None

        # .MER longitudes are given as, e.g., "-14122.6800" (degrees decimal minutes) where the first
        # 4 chars are the degrees (= W141deg22.6800mn) in .LOG parlance, with an extra precision here
        longitude = re.findall(r" LON=([+,-])(\d{3})(\d+\.\d+)", gps_mer)
        if len(longitude) > 0:
            rawstr_dict['longitude'] = re.search("LON=(.*) />", gps_mer).group(1)
            longitude = longitude[0]
            if longitude[0] == "+":
                sign = 1
            elif longitude[0] == "-":
                sign = -1
            longitude = sign*(float(longitude[1]) + float(longitude[2])/60.)
        else:
            longitude = None

        # .MER clockdrifts are given as, e.g.,
        # "<DRIFT YEAR=48 MONTH=7 DAY=4 HOUR=12 MIN=41 SEC=20 USEC=-563354 />"
        # which describe the drift using the sign convention of "drift = gps_time - mermaid_time"
        # (manual Ref: 452.000.852, pg. 32), NB: not all (any?) fields must exist (this is a
        # variable-length string); very often only USEC=*" will exist
        clockdrift = re.findall("<DRIFT( [^>]+) />", gps_mer)
        if len(clockdrift) > 0:
            rawstr_dict['clockdrift'] = re.search(r"<DRIFT (.*) />", gps_mer).group(1)
            clockdrift = clockdrift[0]
            _df = 0
            catch = re.findall(r" USEC=(-?\d+)", clockdrift)
            if catch:
                _df += 10 ** (-6) * float(catch[0])
            catch = re.findall(r" SEC=(-?\d+)", clockdrift)
            if catch:
                _df += float(catch[0])
            catch = re.findall(r" MIN=(-?\d+)", clockdrift)
            if catch:
                _df += 60 * float(catch[0])
            catch = re.findall(r" HOUR=(-?\d+)", clockdrift)
            if catch:
                _df += 60 * 60 * float(catch[0])
            catch = re.findall(r" DAY=(-?\d+)", clockdrift)
            if catch:
                _df += 24 * 60 * 60 * float(catch[0])
            catch = re.findall(r" MONTH=(-?\d+)", clockdrift)
            if catch:
                # An approximation of 30 days per month is sufficient this is just to see if there is something
                # wrong with the drift
                _df += 30 * 24 * 60 * 60 * float(catch[0])
            catch = re.findall(r" YEAR=(-?\d+)", clockdrift)
            if catch:
                _df += 365 * 24 * 60 * 60 * float(catch[0])
            clockdrift = _df
        else:
            clockdrift = None

        clockfreq = re.findall(r"<CLOCK Hz=(-?\d+)", gps_mer)
        if len(clockfreq) > 0:
            clockfreq = clockfreq[0]
            clockfreq = int(clockfreq)
        else:
            clockfreq = None

        # Check if there is an error of clock synchronization
        # if clockfreq <= 0:
            # err_msg = "WARNING: Error with clock synchronization in file \"" + mer_environment_name + "\"" \
            #        + " at " + fixdate.isoformat() + ", clockfreq = " + str(clockfreq) + "Hz"
            # print err_msg

        # Add date to the list
        if fixdate is not None and latitude is not None and longitude is not None and clockdrift \
           is not None and clockfreq is not None:
                gps_out.append(GPS(date=fixdate,
                                             latitude=latitude,
                                             longitude=longitude,
                                             clockdrift=clockdrift,
                                             clockfreq=clockfreq,
                                             source=mer_environment_name,
                                             rawstr_dict=rawstr_dict))
        else:
            raise ValueError

    gps_out = sorted(gps_out, key=lambda x: x.date)
    return gps_out


def get_gps_from_log_content(log_name, log_content):
    '''

        Collect GPS fixes from LOG files within an inclusive datetime range

    '''
    gps_out = []
    gps_log_list = log_content.split("GPS fix...")[1:]
    for gps_log in gps_log_list:
        rawstr_dict = {'fixdate': None, 'latitude': None, 'longitude': None, 'clockdrift': None}
        # .LOG GPS times are given as integer UNIX Epoch times prepending the latitude longitude line
        # .LOG latitudes are given as, e.g., "S22deg33.978mn" (degrees and decimal minutes)
        latitude = re.findall(r"(\d+):\[\w+ *, *\d+\]([S,N])(\d+)deg(\d+.\d+)mn", gps_log)
        if len(latitude) > 0:
            rawstr_dict['latitude'] = re.search(r"[S,N][0-9]+deg[0-9]+\.[0-9]+mn", gps_log).group(0)
            latitude = latitude[0]
            fixdate = latitude[0]
            rawstr_dict['fixdate'] = fixdate
            fixdate = UTCDateTime(int(fixdate))
            if latitude[1] == "N":
                sign = 1
            elif latitude[1] == "S":
                sign = -1
            latitude = sign*(float(latitude[2]) + float(latitude[3])/60.)
        else:
            fixdate = None
            latitude = None

        # .LOG latitudes are given as, e.g., "W141deg22.679mn" (degrees and decimal minutes)
        longitude = re.findall(r"([E,W])(\d+)deg(\d+.\d+)mn", gps_log)
        if len(longitude) > 0:
            rawstr_dict['longitude'] = re.search(r"[E,W][0-9]+deg[0-9]+\.[0-9]+mn", gps_log).group(0)
            longitude = longitude[0]
            if longitude[0] == "E":
                sign = 1
            elif longitude[0] == "W":
                sign = -1
            longitude = sign*(float(longitude[1]) + float(longitude[2])/60.)
        else:
            longitude = None

        hdop = re.findall(r"hdop (\d+.\d+)", gps_log)
        if len(hdop) > 0:
            hdop = hdop[0]
            hdop = float(hdop)
        else:
            hdop = None

        vdop = re.findall(r"vdop (\d+.\d+)", gps_log)
        if len(vdop) > 0:
            vdop = vdop[0]
            vdop = float(vdop)
        else:
            vdop = None

        clockdrift = re.findall(r"GPSACK:(.\d+),(.\d+),(.\d+),(.\d+),(.\d+),(.\d+),(.\d+)?;", gps_log)
        if len(clockdrift) > 0:
            clockdrift = clockdrift[0]
            rawstr_dict['clockdrift'] = clockdrift
            # YEAR + MONTH + DAY + HOUR + MIN + SEC + USEC
            clockdrift = 365 * 24 * 60 * 60 * float(clockdrift[0]) \
                + 30 * 24 * 60 * 60 * float(clockdrift[1]) \
                + 24 * 60 * 60 * float(clockdrift[2]) \
                + 60 * 60 * float(clockdrift[3]) \
                + 60 * float(clockdrift[4]) \
                + float(clockdrift[5]) \
                + 10 ** (-6) * float(clockdrift[6])
        else:
            clockdrift = None

        clockfreq = re.findall(r"GPSOFF:(-?\d+);", gps_log)
        if len(clockfreq) > 0:
            clockfreq = clockfreq[0]
            clockfreq = int(clockfreq)
        else:
            clockfreq = None

        if fixdate is not None and latitude is not None and longitude is not None:
            gps_out.append(GPS(date=fixdate,
                                             latitude=latitude,
                                             longitude=longitude,
                                             clockdrift=clockdrift,
                                             clockfreq=clockfreq,
                                             hdop=hdop,
                                             vdop=vdop,
                                             source=log_name,
                                             rawstr_dict=rawstr_dict))

    gps_out = sorted(gps_out, key=lambda x: x.date)
    return gps_out
