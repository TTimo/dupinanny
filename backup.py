#!/usr/bin/env python

##########################################################################
#    dupinanny backup scripts for duplicity
#    Copyright (C) 2008 Timothee Besset
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
##########################################################################

from __future__ import with_statement
from contextlib import contextmanager

import sys, commands, os, subprocess, pickle, datetime

import config, lock

class Backup( config.ConfigBase ):
    def __init__( self, conf ):
        config.ConfigBase.__init__( self, conf )

    @contextmanager
    def ManageLock( self ):
        filelock = lock.lock( self.lockfile, 'dupinanny backup' )
        filelock.acquire( wait = None, expire = None )
        yield
        filelock.release()

    def Prepare( self ):
        if ( self.dupi.has_key( 'prepare' ) ):
            for p in self.dupi['prepare']:
                p.Prepare( self )

    def Posthook( self ):
        if ( self.dupi.has_key( 'posthook' ) ):
            for p in self.dupi['posthook']:
                p.Posthook( self )

    def ProcessBackups( self ):
        backup_time_filename = os.path.join( os.path.dirname( self.lockfile ), 'dupinnany_backup_info.pickle' )
        if ( not self.dry_run and self.config.has_key( 'backup_every' ) and os.path.exists( backup_time_filename ) ):
            # check last backup information, early out if we haven't reached that point yet
            backup_time_file = file( backup_time_filename )
            last_backup = pickle.load( backup_time_file )
            backup_time_file.close()
            delta = datetime.datetime.now() - last_backup
            if ( delta.days < self.config['backup_every'] ):
                print( 'Last backup is %d days old, no new backup needed.' % delta.days )
                return

        if ( not self.dupi.has_key( 'items' ) ):
            raise Exception( 'no backups defined (\'items\' entry in the DupiConfig dictionary)' )

        # setup first so we can flag 'full backup'
        # and do the cleanup and status summary at the end too

        print '###########################################################################'
        print 'setup'
        print '###########################################################################'
        
        for b in self.dupi['items']:
            b.Setup( self )
            
        for b in self.dupi['items']:
            print '###########################################################################'
            print 'run %s' % b.root
            print '###########################################################################'
            b.Run()

        for b in self.dupi['items']:
            print '###########################################################################'
            print 'finish %s' % b.root
            print '###########################################################################'
            b.Finish()

        if ( not self.dry_run ):
            # write out a global flag to mark the time of the last successful backup run
            # place this in the same folder as the pid file
            backup_time_file = file( backup_time_filename, 'w' )
            pickle.dump( datetime.datetime.now(), backup_time_file )
            backup_time_file.close()

    def Run( self ):
        with self.ManageLock():
            self.Prepare()
            self.ProcessBackups()
            self.Posthook()

class CheckMount( object ):
    def __init__( self, directory ):
        self.directory = directory
                  
    def Prepare( self, backup ):
        print 'CheckMount.Prepare'
        cmd = 'cat /etc/mtab | grep "%s"' % self.directory
        print cmd
        ( status, output ) = commands.getstatusoutput( cmd )
        if ( status != 0 ):
            print repr( ( status, output ) )
            cmd = 'mount "%s"' % self.directory
            print cmd
            ( status, output ) = commands.getstatusoutput( cmd )
            print repr( ( status, output ) )
            if ( status != 0 ):
                raise Exception( 'CheckMount: %s is not mounted' % self.directory )

class BackupTarget( object ):
    def __init__( self, root, destination, exclude = [], shortFilenames = False , include = [] ):
        self.root = root
        self.destination = destination
        self.exclude = exclude
        self.include = include
        self.backup = None
        self.shortFilenames = shortFilenames
        self.fullFileFlag = os.path.normpath( '%s.full' % root.replace( '/', '_' ) )

    def Setup( self, backup ):
        self.backup = backup
        print 'BackupTarget.Setup %s' % repr( ( self.root, self.destination, self.exclude, self.include ) )

        if ( self.backup.full ):
            subprocess.check_call( [ 'touch', self.fullFileFlag ] )

        if ( os.path.exists( self.fullFileFlag ) ):
            full = 'full backup enabled'
        else:
            full = 'not present'	
        print 'full backup indicator file: %s - %s' % ( repr( self.fullFileFlag ), full )

    def Run( self, recursed = False ):

        # we do it that way so a full backup that fails keeps getting retried until it works
        backup_type = 'incremental'
        if ( os.path.exists( self.fullFileFlag ) ):
            backup_type = 'full'

        if ( self.backup.config.has_key( 'password' ) ):
            os.environ['PASSPHRASE'] = self.backup.config['password']

        option_string = []
        for e in self.exclude:
            option_string.append( '--exclude=%s' % e )
        for e in self.include:
            option_string.append( '--include=%s' % e )
        if ( self.shortFilenames ):
            option_string.append( '--short-filenames' )
        if ( self.backup.config.has_key('duplicity_args') ):
            option_string += self.backup.config['duplicity_args']

        tempdir = '/tmp'
        try:
            tempdir = os.environ['TEMP']
        except:
            pass
        if ( self.backup.config.has_key('tempdir') ):
            tempdir = self.backup.config['tempdir']
            # need to make it explicit then
            option_string += [ '--tempdir', tempdir ]

        # avoid a bad recursion problem in 5.0.2 - make sure to skip the tempdir
        # I don't know if this has been fixed in newer releases of duplicity, would be worth checking
        # additional difficulty: can only do this if the directory is actually in the path
        if ( tempdir.find( self.root ) != -1 ):
            if ( tempdir is None ):
                option_string.append( '--exclude=/tmp' )
            else:
                option_string.append( '--exclude=%s' % tempdir )

        cmd = [ self.backup.duplicity, backup_type, '--asynchronous-upload' ]
        cmd += option_string
        cmd.append( self.root )
        cmd.append( self.destination )
        print repr( cmd )

        if ( not self.backup.dry_run ):
            p = subprocess.Popen( cmd, stdin = None, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, shell = False )
            # p.communicate is nice, but I want to print output as we go
            # NOTE: using a tee class would be a better way to do this clearly
            failed_incremental = False
            ret = None
            while ( ret is None ):
                out = p.stdout.read()
                if ( len( out ) != 0 ):
                    sys.stdout.write( out )
                    if ( out.find( 'Old signatures not found and incremental specified' ) != -1 ):
                        failed_incremental = True
                ret = p.poll()
                print repr( ret )
            if ( ret != 0 ):
                if ( failed_incremental ):
                    print 'no incremental found, forcing full backup'
                    if ( recursed ):
                        raise Exception( 'already recursed while forcing full backup' )
                    subprocess.check_call( [ 'touch', self.fullFileFlag ] )
                    self.Run( recursed = True )
                    return
                raise Exception( 'backup failed' )

	    # clear the full flag if needed
            if ( backup_type == 'full' ):
                os.unlink( self.fullFileFlag )

        option_string = [ '--extra-clean' ]
        if ( self.shortFilenames ):
            option_string.append( '--short-filenames' )
        if ( self.backup.config.has_key('duplicity_args') ):
            option_string += self.backup.config['duplicity_args']

        cmd = [ self.backup.duplicity, 'cleanup' ]
        cmd += option_string
        cmd.append( '--force' )
        cmd.append( self.destination )
        print( repr( cmd ) )
        if ( self.backup.cleanup or not self.backup.dry_run ):
            subprocess.check_call( cmd )

        if ( self.backup.remove_older != 0 ):
            cmd = [ self.backup.duplicity, 'remove-older-than', '%dD' % self.backup.remove_older, '--force' ]
            cmd += option_string
            cmd.append( self.destination )
            print( repr( cmd ) )
            if ( self.backup.force_remove_older or not self.backup.dry_run ):
                subprocess.check_call( cmd )

    def Finish( self ):
        option_string = []
        if ( self.shortFilenames ):
            option_string.append( '--short-filenames' )
        if ( self.backup.config.has_key('duplicity_args') ):
            option_string += self.backup.config['duplicity_args']
        cmd = [ self.backup.duplicity, 'collection-status' ]
        cmd += option_string
        cmd.append( self.destination )
        print( repr( cmd ) )
        subprocess.check_call( cmd )

class LVMBackupTarget( BackupTarget ):
    def __init__( self, root, destination, lvmpath, snapsize, snapshot_name, snapshot_path, exclude = [], shortFilenames = False ):
        BackupTarget.__init__( self, root, destination, exclude = exclude, shortFilenames = shortFilenames )
        self.lvmpath = lvmpath
        self.snapsize = snapsize
        self.snapshot_name = snapshot_name
        self.snapshot_path = snapshot_path
        # otherwrite the parent class's name to avoid collisions
        self.fullFileFlag = os.path.normpath( '%s.full' % lvmpath.replace( '/', '_' ) )

    def Run( self, recursed = False ):
        # create snapshot
        if ( not recursed ): # only done once at top level, recursed is the path for 'try again with a full backup'
            cmd = [ 'lvcreate', '-s', '-L', self.snapsize, '-n', self.snapshot_name, self.lvmpath ]
            print cmd
            subprocess.check_call( cmd )
            cmd = [ 'mount', '-t', 'auto', self.snapshot_path, self.root ]
            print cmd
            subprocess.check_call( cmd )
        try:
            BackupTarget.Run( self, recursed = recursed )
        finally:
            if ( not recursed ): # only done once at top level, recursed is the path for 'try again with a full backup'            
                # release snapshot - making sure to do that in a cleanup handler so we release the snap no matter what
                cmd = [ 'umount', self.root ]
                print cmd
                subprocess.check_call( cmd )
                cmd = [ 'lvremove', '-f', self.snapshot_path ]
                print cmd
                subprocess.check_call( cmd )

if ( __name__ == '__main__' ):
    import config
    backup = config.readConfig( sys.argv )
    backup['backup'].Run()
