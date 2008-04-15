#!/usr/bin/env python

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

        # setup all 3 first so we can flag 'full backup'
        # and do the cleanup and status summary at the end too
        
        for b in self.dupi['items']:
            b.Setup( self )
            
        for b in self.dupi['items']:
            b.Run()

        for b in self.dupi['items']:
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

class FileSystemBackup:
    def __init__( self, root, destination, exclude = [] ):
        self.root = root
        self.destination = destination
        self.exclude = exclude
        self.backup = None

    def CheckTargetDirectory( self ):
        if ( not os.path.exists( self.destination ) ):
            print 'create backup directory %s' % self.destination
            os.makedirs( self.destination )
        else:
            assert( os.path.isdir( self.destination ) )

    def Setup( self, backup ):
        self.backup = backup
        print 'FileSystemBackup.Setup %s' % repr( ( self.root, self.destination, self.exclude ) )
        self.CheckTargetDirectory()

        if ( self.backup.full ):
            ret = os.system( 'touch "%s"' % os.path.join( self.destination, 'full' ) )
            if ( ret != 0 ):
                raise Exception( 'failed to write the full backup flag' )

    def Run( self, recursed = False ):

        # we do it that way so a full backup that fails keeps getting retried until it works
        backup_type = 'incremental'
        if ( os.path.exists( os.path.join( self.destination, 'full' ) ) ):
            backup_type = 'full'

        os.environ['PASSPHRASE'] = self.backup.config['password']

        exclude_string = ''
        for e in self.exclude:
            exclude_string += '--exclude "%s" ' % e
        cmd = '%s %s --volsize 100 --short-filenames %s--exclude-other-filesystems %s file://%s' % ( self.backup.duplicity, backup_type, exclude_string, self.root, self.destination )
        print cmd
        if ( not self.backup.dry_run ):
            p = subprocess.Popen( cmd, stdin = None, stdout = subprocess.PIPE, stderr = subprocess.STDOUT, shell = True )
            # p.communicate is nice, but I want to print output as we go
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
                    ret = os.system( 'touch "%s"' % os.path.join( self.destination, 'full' ) )
                    if ( ret != 0 ):
                        raise Exception( 'failed to write the full backup flag' )
                    self.Run( recursed = True )
                    return
                raise Exception( 'backup failed' )

        # clear the full flag if needed
        if ( backup_type == 'full' ):
            os.unlink( os.path.join( self.destination, 'full' ) )

        cmd = '%s cleanup --short-filenames --force file://%s' % ( self.backup.duplicity, self.destination )
        print cmd
        if ( not self.backup.dry_run ):
            ret = os.system( cmd )
            if ( ret != 0 ):
                raise Exception( 'remove-older-than failed' )
        
        cmd = '%s remove-older-than 4D --short-filenames --force file://%s' % ( self.backup.duplicity, self.destination )
        print cmd
        if ( not self.backup.dry_run ):
            ret = os.system( cmd )
            if ( ret != 0 ):
                raise Exception( 'remove-older-than failed' )


    def Finish( self ):
        cmd = '%s collection-status --short-filenames file://%s' % ( self.backup.duplicity, self.destination )
        print cmd
        ret = os.system( cmd )
        if ( ret != 0 ):
            raise Exception( 'collection-status failed' )


if ( __name__ == '__main__' ):
    import config
    backup = config.readConfig( sys.argv )
    backup['backup'].Run()
