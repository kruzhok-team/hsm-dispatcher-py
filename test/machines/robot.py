# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The test machine written in Python: the code is functions
#
#  Copyright (C) 2026 Alexey Fedoseev <aleksey@fedoseev.net>
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program. If not, see https://www.gnu.org/licenses/
#
#  -----------------------------------------------------------------------------

# pylint: disable=undefined-variable,global-statement

import hsmd


def idle_entry():
    log.print('idle')


def go_guard():
    return event.speed > 3


def work_entry():
    global steps
    steps = 0


def work_tick():
    global steps
    steps += 1
    log.print('step {}'.format(steps))


def broken():
    global steps
    steps = 0
    steps = 1 / steps


machine = hsmd.Machine('Robot', id='R', states=[
    hsmd.Initial(id='init'),
    hsmd.State('Idle', id='idle', entry=idle_entry, internal=[
        hsmd.On('PING', action="log.print('pong')"),
        hsmd.On('BREAK', action=broken),
    ]),
    hsmd.State('Work', id='work', entry=work_entry, internal=[
        hsmd.On('TICK', action=work_tick),
    ], states=[
        hsmd.Initial(id='work-init'),
        hsmd.State('Step', id='step'),
    ]),
    hsmd.Choice(id='again'),
    hsmd.Final(id='fin'),
], transitions=[
    hsmd.Transition('init', 'idle'),
    hsmd.Transition('idle', 'work', 'GO', guard=go_guard),
    hsmd.Transition('work-init', 'step'),
    hsmd.Transition('work', 'again', 'STOP'),
    hsmd.Transition('again', 'idle', guard='event.again'),
    hsmd.Transition('again', 'fin', guard=hsmd.ELSE),
], components=[
    hsmd.Declaration('log', 'Log'),
])
