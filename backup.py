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

import sys, commands, os, subprocess

import config, lock

class Backup( config.ConfigBase ):
    def __init__( self, conf ):
        config.ConfigBase.__init__( self, conf )
        self.lock = None

    def AcquireLock( self ):
        self.lock = lock.lock( self.lockfile, 'dupinanny backup' )
        self.lock.acquire( wait = None, expire = None )

    def Prepare( self ):
        if ( self.dupi.has_key( 'prepare' ) ):
            for p in self.dupi['prepare']:
                p.Prepare( self )

    def ProcessBackups( self ):
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

    def Run( self ):
        self.AcquireLock()
        self.Prepare()
        self.ProcessBackups()

class CheckMount:
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

class BackupTarget:
    def __init__( self, root, destination, exclude = [], shortFilenames = False ):
        self.root = root
        self.destination = destination
        self.exclude = exclude
        self.backup = None
        self.shortFilenames = shortFilenames
        self.fullFileFlag = os.path.normpath( '%s.full' % root.replace( '/', '_' ) )

    def CheckTargetDirectory( self ):
        # was relevant to local filesystem backup
        # TODO: this needs done over rsync as well
#        if ( not os.path.exists( self.destination ) ):
#            print 'create backup directory %s' % self.destination
#            os.makedirs( self.destination )
#        else:
#            assert( os.path.isdir( self.destination ) )
        pass

    def Setup( self, backup ):
        self.backup = backup
        print 'BackupTarget.Setup %s' % repr( ( self.root, self.destination, self.exclude ) )
        self.CheckTargetDirectory()	

        if ( self.backup.full ):
            ret = os.system( 'touch "%s"' % self.fullFileFlag )
            if ( ret != 0 ):
                raise Exception( 'failed to write the full backup flag' )

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

        os.environ['PASSPHRASE'] = self.backup.config['password']

        option_string = ''
        for e in self.exclude:
            option_string += '--exclude "%s" ' % e
        if ( self.shortFilenames ):
            option_string += '--short-filenames '
        # TMP avoid a bad recursion problem in 5.0.2 - make sure to always skip /tmp
        # and .. duplicity doesn't like getting /tmp when it's not in the root
        exclude_tmp = ''
        if ( self.root == '/' ):
            exclude_tmp = '--exclude /tmp'
        cmd = '%s %s --asynchronous-upload --volsize 100 %s %s --exclude-other-filesystems %s %s' % ( self.backup.duplicity, backup_type, option_string, exclude_tmp, self.root, self.destination )
        print cmd
        if ( not self.backup.dry_run ):
            p = subprocess.Popen( cmd, stdin = None, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, shell = True )
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
                    ret = os.system( 'touch "%s"' % self.fullFileFlag )
                    if ( ret != 0 ):
                        raise Exception( 'failed to write the full backup flag' )
                    self.Run( recursed = True )
                    return
                raise Exception( 'backup failed' )

	    # clear the full flag if needed
            if ( backup_type == 'full' ):
                os.unlink( self.fullFileFlag )

        option_string = ''
        if ( self.shortFilenames ):
            option_string += '--short-filenames '

        cmd = '%s cleanup %s--force %s' % ( self.backup.duplicity, option_string, self.destination )
        print cmd
        if ( self.backup.cleanup or not self.backup.dry_run ):
            ret = os.system( cmd )
            if ( ret != 0 ):
                raise Exception( 'cleanup failed' )

        if ( self.backup.remove_older != 0 ):
            cmd = '%s remove-older-than %dD --force %s%s' % ( self.backup.duplicity, self.backup.remove_older, option_string, self.destination )
            print cmd
            if ( self.backup.force_remove_older or not self.backup.dry_run ):
                ret = os.system( cmd )
                if ( ret != 0 ):
                    raise Exception( 'remove-older-than failed' )

    def Finish( self ):
        option_string = ''
        if ( self.shortFilenames ):
            option_string += '--short-filenames '
        cmd = '%s collection-status %s%s' % ( self.backup.duplicity, option_string, self.destination )
        print cmd
        ret = os.system( cmd )
        if ( ret != 0 ):
            raise Exception( 'collection-status failed' )

if ( __name__ == '__main__' ):
    import config
    backup = config.readConfig( sys.argv )
    backup['backup'].Run()
