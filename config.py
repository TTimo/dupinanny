#!/usr/bin/env python

import os, re

from optparse import OptionParser

class ConfigBase:
    def __init__( self, dupi ):
        self.dupi = dupi
        self.config = dupi['config']
        
        self.lockfile = self.config['lockfile']
        
        # NOTE: may get an override from command line
        self.dry_run = False
        try:
            self.dry_run = self.config['dry_run']
        except:
            pass

        self.duplicity = 'duplicity'
        try:
            self.duplicity = self.config['duplicity']
        except:
            pass

    def commandLineOverrides( self, options ):
        if ( options.dry_run ):
            self.dry_run = options.dry_run

        if ( self.dry_run ):
            print '*** running in test mode ***'

        self.full = options.full
        if ( self.full ):
            print '*** FLAGING FULL BACKUP ***'

def readConfig( cmdargs ):

    parser = OptionParser()
    parser.add_option( '--dry-run', action = 'store_true', dest = 'dry_run', help = 'show commands, do not execute' )
    parser.add_option( '--config', action = 'store', type = 'string', dest = 'configFile', default = 'config.cfg.example', help = 'use this config file' )
    parser.add_option( '--full', action = 'store_true', dest = 'full', help = 'do a full backup' )
    ( options, args ) = parser.parse_args( cmdargs )
    
    globals = {}
    locals = {}
    try:
        execfile( options.configFile, globals, locals )
    except:
        print 'exception raised while reading config file %s' % options.configFile
        raise
    if ( not locals.has_key( 'DupiConfig' ) ):
        raise 'DupiConfig dictionary was not defined'
    DupiConfig = locals['DupiConfig']
    
    # setup default backup class if needed
    if ( not DupiConfig.has_key( 'backup' ) ):
        from backup import Backup
        DupiConfig['backup'] = Backup( DupiConfig )

    DupiConfig['backup'].commandLineOverrides( options )
    
    return DupiConfig

if ( __name__ == '__main__' ):
    readConfig()

