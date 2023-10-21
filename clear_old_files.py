'''
@author:     Dirk Ludwig

@license:    license
 
@deffield    updated: Updated
'''

import sys
import re
import os
import stat
import paramiko
import time
import datetime

from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter

__all__ = []
__version__ = 0.1
__date__ = '2023-10-20'
__updated__ = '2023-10-21'

DEBUG = 0
TESTRUN = 0
PROFILE = 0

#global variables
verbose = 0

class CLIError(Exception):
    '''Generic exception to raise and log different fatal errors.'''
    def __init__(self, msg):
        super(CLIError).__init__(type(self))
        self.msg = "E: %s" % msg
    def __str__(self):
        return self.msg
    def __unicode__(self):
        return self.msg




def ftp_login(ftphost,ftpuser,ftppass): 
    ftp = ftplib.FTP(host=ftphost,user=ftpuser,passwd=ftppass)
    return ftp



def open_sftp_connection(host, user, passwd):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, 22, user, passwd)
    assert ssh.get_transport().is_active(), 'Failed to connect to server'
    #needs to return ssh and connection otherwise ssh is garbage collected and dropped
    return ssh, ssh.open_sftp()

    
def v_print(lvl, *text):
    if verbose >= lvl:
        print(*text)


def del_older_than(connection, path, cutoff, exclude_re=None, dryrun=True):
    v_print(3, "checking path:", path)
    dirlist = connection.listdir_attr(path)
    count = 0
    maxage = 0
    size = 0
    alltogo = True


    for direntry in dirlist: #connection.listdir_iter(path):
        if exclude_re:
            if exclude_re.search(direntry.filename):
                v_print(1, "matched exclude pattern, skipping ", direntry)
                alltogo = False
                continue

        if(stat.S_ISDIR(direntry.st_mode)):
            v_print(3, "directory: ", str(direntry.st_mtime), str(direntry.st_mode), " -->", str(direntry.filename));
            subcount, subsize, submax, suballtogo = del_older_than(connection, os.path.join(path, direntry.filename), cutoff, exclude_re, dryrun)
            count += subcount
            size += subsize
            if suballtogo == False:
                alltogo = False
            else:
                if dryrun:
                    v_print(2, "dry-run / list-only, not removing dir : ", direntry.filename)
                else:
                    v_print(2, "deleting dir : ", direntry)
                    connection.rmdir(os.path.join(path, direntry.filename))
                    

            if submax > maxage:
                maxage = submax

        else:            
            if direntry.st_mtime < cutoff:
                candidate = True
                count += 1
                size += direntry.st_size
                if dryrun:
                    v_print(2, "dry-run / list-only, not removing file: ", direntry.filename)
                else:                    
                    v_print(2, "removing file: ", direntry)
                    connection.remove(os.path.join(path, direntry.filename))
                   
                
            else:
                candidate = False
                alltogo = False

            v_print(3, "direntry : ", str(direntry.st_mtime), str(direntry.st_mode), " ", "X " if candidate else "  ", str(direntry.filename));
            
            if direntry.st_mtime > maxage:
                maxage = direntry.st_mtime 


    v_print(3, "done with path:", path)

    return count, size, maxage, alltogo




def main(argv=None): 
    '''Command line options.'''
    
    if argv is None:
        argv = sys.argv
    else:
        sys.argv.extend(argv)

    program_name = os.path.basename(sys.argv[0])
    program_version = "v%s" % __version__
    program_build_date = str(__updated__)
    program_version_message = '%%(prog)s %s (%s)' % (program_version, program_build_date)
    program_shortdesc = __import__('__main__').__doc__.split("\n")[1]
    program_license = '''%s

  Created by Dirk Ludwig on %s.
  Recursively searches through folders and deletes files older than a specified time. Removes any sub-directories that get emptied during processing.
  Output is quiet by default, use -vv for a reasonable verbosity level.
  Currently only supports sftp connections.
  
USAGE
   example: 

      %s -h localhost -u joseph -p secretz -t 100 -vv -l
''' % (program_shortdesc, str(__date__), os.path.basename(__file__))

    try:
        # Setup argument parser
        parser = ArgumentParser(description=program_version_message +"\n"+program_license, formatter_class=RawDescriptionHelpFormatter, add_help=False)
        parser.add_argument('-h', '--host', required=True, action="store", help="ftp host to connect to" )
#######################
## TODO add support for plain FTP
# parser.add_argument('-f', '--ftp', action="store_true", default=False, help="Whether to use ftp to make the connection 0 False, 1 True [default %(default)s]")
        parser.add_argument("-v", "--verbose", dest="verbose", action="count", default=0, help="increase verbosity level e.g. -vv [default: %(default)s]")
################
## TODO add functionality for include
#        parser.add_argument("-i", "--include", dest="include", help="NOT IMPLEMENTED YET -- only include paths matching this regex pattern. Note: exclude is given preference over include. [default: %(default)s]", metavar="RE" )
        parser.add_argument("-e", "--exclude", dest="exclude", default=None, help="exclude paths matching this regex pattern. [default: %(default)s]", metavar="RE" )
        #parser.add_argument('-V', '--version', action='version', version=program_version_message)
        parser.add_argument('-u', '--user', action="store", help="username. [default: %(default)s]", default='anonymous' )
        parser.add_argument("-p", '--password', action="store", help="password")
        parser.add_argument("-?", '--help',  action="help", help="Display this help/usage message")
        parser.add_argument('-d', '--directory', action="store", default='.', help="the ftp directory to start searching from")
        parser.add_argument('-t', '--age', dest="age", action="store", default=0.0, metavar="AGE", type=float, help="the minimum age in days a directory must be before considered for deletion (1 hour = 0.04167 days) [default: %(default)s]")
        parser.add_argument("-l", '--list-only', dest="listOnly", default=False, action="store_true", help="only list the directories, don't actually delete anything [default: %(default)s]")
        
        # Process arguments
        args = parser.parse_args()
        
        global verbose 
        verbose = args.verbose
        inpat = "inpat" #args.include
        if args.exclude:
            expat = re.compile(args.exclude)
        else:
            expat = None

        # age will be in days so in seconds --> days * 3600 * 24
        cutoff = time.time() - args.age * 3600 * 24 #
        
        if verbose > 0:
            print("Verbose mode on")
            print("----------------------------------------------------------")
            print("username       :", args.user)
            print("host           :", args.host)
            print("directory      :", args.directory)
            print("exclude pattern:", expat)
            print("nodelete       :", str(args.listOnly))
            print("min file age   :", str(args.age), " days,  => keep files newer than ", datetime.datetime.fromtimestamp(cutoff))
            print("----------------------------------------------------------")
                
        if inpat and expat and inpat == expat:
            raise CLIError("include and exclude pattern are equal! Nothing will be processed.")
       
        #if args.sftp:
        ssh, ftp = open_sftp_connection(args.host,args.user,args.password)
        #else:
        #    ftp = ftp_connect(args.host,args.user,args.password)
        
        count, size, maxage, alltogo = del_older_than(ftp, args.directory, cutoff, expat, args.listOnly)
        v_print(1, "found files: ", count,", size= ",size, ", newest= ", datetime.datetime.fromtimestamp(maxage), ", allgone=",alltogo)
         
        return 0
    
    except KeyboardInterrupt:
        ### handle keyboard interrupt ###
        print( "operation interrupted by user: Exiting")
        return 0
    except Exception as e:
        if DEBUG or TESTRUN:
            raise(e)
        indent = len(program_name) * " "
        sys.stderr.write(program_name + ": " + repr(e) + "\n")
        sys.stderr.write(indent + "  for help use --help\n")
        return 2

if __name__ == "__main__":
    if DEBUG:
        #sys.argv.append("-?")
        sys.argv.append("-v")
    if TESTRUN:
        import doctest
        doctest.testmod()
    if PROFILE:
        import cProfile
        import pstats
        profile_filename = 'clear_old_ftp_profile.txt'
        cProfile.run('main()', profile_filename)
        statsfile = open("clear_old_ftp_profile_stats.txt", "wb")
        p = pstats.Stats(profile_filename, stream=statsfile)
        stats = p.strip_dirs().sort_stats('cumulative')
        stats.print_stats()
        statsfile.close()
        sys.exit(0)
    sys.exit(main())
