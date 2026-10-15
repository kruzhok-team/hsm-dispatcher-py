# -----------------------------------------------------------------------------
#  The Python HSM dispatcher
#
#  The declarations that break the rules of a document
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

import hsmd

two_initials = hsmd.Machine('A', states=[
    hsmd.Initial(id='i1'), hsmd.Initial(id='i2'), hsmd.State('S'),
], transitions=[hsmd.Transition('i1', 'S'), hsmd.Transition('i2', 'S')])

unknown_target = hsmd.Machine('B', states=[
    hsmd.Initial(), hsmd.State('S'),
], transitions=[hsmd.Transition('B.initial', 'T')])

no_event = hsmd.Machine('C', states=[
    hsmd.Initial(), hsmd.State('S', internal=[hsmd.On('', action='pass')]),
], transitions=[hsmd.Transition('C.initial', 'S')])

same_id = hsmd.Machine('D', states=[
    hsmd.Initial(), hsmd.State('S'), hsmd.State('S'),
], transitions=[hsmd.Transition('D.initial', 'S')])

not_code = hsmd.Machine('E', states=[
    hsmd.Initial(), hsmd.State('S', entry=42),
], transitions=[hsmd.Transition('E.initial', 'S')])

no_initial = hsmd.Machine('F', states=[hsmd.State('S')])

event_on_initial = hsmd.Machine('G', states=[
    hsmd.Initial(), hsmd.State('S'),
], transitions=[hsmd.Transition('G.initial', 'S', 'GO')])
