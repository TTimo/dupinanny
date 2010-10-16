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

# a class version for easy lock operation based on the portalocker module
# NOTE: the lock has to be released and does not expire
# when the object goes out of scope it will try to release

import sys, os, pickle, portalocker, datetime, time, platform, subprocess

class lock( object ):
    def __init__( self, lockfile, lockinfo, debug = True ):
        self.lockfile = lockfile
        self.lockinfo = lockinfo
        self.handle = None
        self.debug = debug

    def checkProcessExists( self, pid ):
        if ( platform.system() == 'Linux' ):
            return os.path.exists( '/proc/%d' % pid )
        if ( platform.system() == 'Darwin' ):
            # surely there's a better way..
            try:
                subprocess.check_call( [ 'ps', '-p', '%d' % pid ], stdout = subprocess.PIPE, stderr = subprocess.PIPE )
                # if this succeeded, then there is a process
                return True
            except:
                return False
        raise Exception( 'Need support for checking for process existence on platform %s' % platform.system() )

    def checkValidLock( self ):
        if ( not os.path.exists( self.lockfile ) ):
            return False
        handle = file( self.lockfile )
        lock_pid = pickle.load( handle )
        lock_expire = pickle.load( handle )
        lock_info = pickle.load( handle )
        handle.close()
        if ( not self.checkProcessExists( lock_pid ) ):
            if ( self.debug ):
                print '%s: stale lock, no such pid %d (%s)' % ( self.lockfile, lock_pid, repr( lock_info ) )
            os.unlink( self.lockfile )
            return False
        if ( lock_expire is None ):
            if ( self.debug ):
                print '%s: active lock pid %d, does not expire (%s)' % ( self.lockfile, lock_pid, repr( lock_info ) )
            return True
        s_lock_expire = lock_expire.ctime()
        if ( datetime.datetime.now() > lock_expire ):
            if ( self.debug ):
                print '%s: active lock pid %d, expired at %s (%s)' % ( self.lockfile, lock_pid, s_lock_expire, repr( lock_info ) )
            # TODO: what now
            # we reply that the lock is active however (could recurse a call to checkValidLock again)
            # if I own the lock however, nuke it now
            if ( lock_pid == os.getpid() ):
                print 'my own lock - remove'
                os.unlink( self.lockfile )
            return True
        if ( self.debug ):
            print '%s: active lock pid %d, expires at %s (%s)' % ( self.lockfile, lock_pid, s_lock_expire, repr( lock_info ) )
        return True

    # pass a total time to wait, 0 for forever, None for abort right away on lock
    # expire indicates when the lock will expire, meaning we allow some other process to steal it, possibly after making sure to kill a stalled AB process
    # pass None as expire for no expiration
    # NOTE: we may need functionality to extend the expiration on an acquired lock
    def acquire( self, wait = 5 * 60, waitInterval = 5, expire = 10 * 60 ):
        waitTotal = 0
        while ( self.checkValidLock() ):
            if ( wait is None ):
                raise Exception( 'lock is busy' )
            else:
                if ( wait != 0 ):
                    waitTotal += waitInterval
                    if ( self.debug ):
                        print( 'waitTotal: %d wait: %d waitInterval: %d' % ( waitTotal, wait, waitInterval ) )
                    if ( waitTotal > wait ):
                        raise Exception( 'exceeded max wait time on the lock' )
                    time.sleep( waitInterval )

        # don't want blocking on acquired locks - even with the loop, there is still a possibility of stolen lock and exception here
        self.handle = file( self.lockfile, 'w' )
        portalocker.lock( self.handle, portalocker.LOCK_EX | portalocker.LOCK_NB )
        if ( self.debug ):
            print( 'acquired lock %s' % self.lockfile )
        pickle.dump( os.getpid(), self.handle )
        if ( expire is None ):
            expire_time = None
        else:
            expire_time = datetime.datetime.now()
            expire_time += datetime.timedelta( seconds = expire )
        pickle.dump( expire_time, self.handle )
        pickle.dump( self.lockinfo, self.handle )
        self.handle.flush()

    def release( self ):
        if ( not self.handle is None ):
            # possible that some other script would print a message about the lock in between the close and the unlink
            self.handle.close()
            os.unlink( self.lockfile )
            self.handle = None

    # don't rely on this - from the python documentation:
    # "It is not guaranteed that __del__() methods are called for objects that still exist when the interpreter exits."
    def __del__( self ):
        self.release()

if ( __name__ == '__main__' ):
    l = lock( os.path.expanduser( '~/testlock' ), 'testlock' )
    l.acquire( wait = 60 )
    print 'acquired. press enter'
    sys.stdin.readline()
    # doing the release in the __del__ doesn't seem to work too well
    l.release()
