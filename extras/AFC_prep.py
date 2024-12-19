# Armored Turtle Automated Filament Changer
#
# Copyright (C) 2024 Armored Turtle
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import os
import json
try:
    from urllib.request import urlopen
except:
    # Python 2.7 support
    from urllib2 import urlopen

class afcPrep:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.delay = config.getfloat('delay_time', 0.1, minval=0.0)
        self.enable = config.getboolean("enable", False)

        # Flag to set once resume rename as occured for the first time
        self.rename_occured = False

    def handle_connect(self):
        """
        Handle the connection event.
        This function is called when the printer connects. It looks up AFC info
        and assigns it to the instance variable `self.AFC`.
        """
        self.AFC = self.printer.lookup_object('AFC')
        self.AFC.gcode.register_command('PREP', self.PREP, desc=None)

    def _rename_resume(self):
        """
            Helper function to check if renaming RESUME macro has occured and renames RESUME.
            Addes a new RESUME macro that points to AFC resume function
        """

        # Checking to see if rename has already been done, don't want to rename again if prep was already ran
        if not self.rename_occured:
            self.rename_occured = True
            # Renaming users Resume macro so that RESUME calls AFC_Resume function instead
            base_resume_name = "RESUME"
            prev_cmd = self.AFC.gcode.register_command(base_resume_name, None)
            if prev_cmd is not None:
                pdesc = "Renamed builtin of '%s'" % (base_resume_name,)
                self.AFC.gcode.register_command(self.AFC.ERROR.AFC_RENAME_RESUME_NAME, prev_cmd, desc=pdesc)
            else:
                self.AFC.gcode.respond_info("{}Existing command {} not found in gcode_macros{}".format("<span class=warning--text>", base_resume_name, "</span>",))

            self.AFC.gcode.register_command(base_resume_name, self.AFC.ERROR.cmd_AFC_RESUME, desc=self.AFC.ERROR.cmd_AFC_RESUME_help)

    def PREP(self, gcmd):
        while self.printer.state_message != 'Printer is ready':
            self.AFC.reactor.pause(self.AFC.reactor.monotonic() + 1)

        self._rename_resume()

        ## load Unit variables
        if os.path.exists(self.AFC.VarFile + '.unit') and os.stat(self.AFC.VarFile + '.unit').st_size > 0:
            self.AFC.lanes=json.load(open(self.AFC.VarFile + '.unit'))
        ## load Toolhead variables
        if os.path.exists(self.AFC.VarFile + '.tool') and os.stat(self.AFC.VarFile + '.tool').st_size > 0:
            self.AFC.extruders=json.load(open(self.AFC.VarFile + '.tool'))
        else:
            self.AFC.extruders={}

        temp=[]

        self.AFC.tool_cmds={}
        for PO in self.printer.objects:
            if 'AFC_stepper' in PO and 'tmc' not in PO:
                LANE=self.printer.lookup_object(PO)
                self.AFC.stepper[LANE.name]=LANE
                temp.append(LANE.name)
                if LANE.extruder_name not in self.AFC.extruders: self.AFC.extruders[LANE.extruder_name]={}
                if LANE.unit not in self.AFC.units: self.AFC.units[LANE.unit] = {}
                if LANE.unit not in self.AFC.lanes: self.AFC.lanes[LANE.unit] = {}
                if LANE.name not in self.AFC.units[LANE.unit]: self.AFC.units[LANE.unit][LANE.name]={}
                if LANE.name not in self.AFC.lanes[LANE.unit]: self.AFC.lanes[LANE.unit][LANE.name] = {}
                if 'spool_id' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.spool_id = self.AFC.lanes[LANE.unit][LANE.name]['spool_id'] 
                if self.AFC.spoolman_ip !=None and LANE.spool_id != None:
                    try:
                        url = 'http://' + self.AFC.spoolman_ip + ':'+ self.AFC.spoolman_port +"/api/v1/spool/" + self.AFC.lanes[LANE.unit][LANE.name]['spool_id']
                        result = json.load(urlopen(url))
                        LANE.material = result['filament']['material']
                        LANE.color = '#' + result['filament']['color_hex']
                        if 'remaining_weight' in result: LANE.weight =  result['remaining_weight']
                    except:
                        self.AFC.ERROR.AFC_error("Error when trying to get Spoolman data for ID:{}".format(self.AFC.lanes[LANE.unit][LANE.name]['spool_id']), False)
                else:
                    if 'material' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.material = self.AFC.lanes[LANE.unit][LANE.name]['material']
                    if 'color' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.color = self.AFC.lanes[LANE.unit][LANE.name]['color']
                    if 'weight' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.weight=self.AFC.lanes[LANE.unit][LANE.name]['weight']

                if 'runout_lane' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.runout_lane = self.AFC.lanes[LANE.unit][LANE.name]['runout_lane']
                if 'map' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.map = self.AFC.lanes[LANE.unit][LANE.name]['map']
                if LANE.map != 'NONE':
                   self.AFC.tool_cmds[LANE.map] = LANE.name

                if 'hub_loaded' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.hub_loaded = self.AFC.lanes[LANE.unit][LANE.name]['hub_loaded']
                if 'tool_loaded' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.tool_loaded = self.AFC.lanes[LANE.unit][LANE.name]['tool_loaded']
                if 'status' in self.AFC.lanes[LANE.unit][LANE.name]: LANE.status = self.AFC.lanes[LANE.unit][LANE.name]['status']
        self.AFC.lanes={}
        self.AFC.save_vars()
        if self.enable == False:
            self.AFC.gcode.respond_info('Prep Checks Disabled')
            return
        elif len(self.AFC.units) >0:
            for UNIT in self.AFC.units.keys():
                logo=''
                logo_error = ''
                try: CUR_HUB = self.printer.lookup_object('AFC_hub '+ UNIT)
                except:
                    error_string = 'Error: Hub for ' + UNIT + ' not found in AFC_Hardware.cfg. Please add the [AFC_Hub ' + UNIT + '] config section.'
                    self.AFC.AFC_error(error_string, False)
                    return
                self.AFC.gcode.respond_info(CUR_HUB.type + ' ' + UNIT +' Prepping lanes')

                logo=CUR_HUB.unit.logo
                logo+='  ' + UNIT + '\n'
                logo_error=CUR_HUB.unit.logo_error
                logo_error+='  ' + UNIT + '\n'

                LaneCheck = True
                for LANE in self.AFC.units[UNIT].keys():
                    if not CUR_HUB.unit.system_Test(UNIT,LANE, self.delay):
                        LaneCheck = False

                if LaneCheck:
                    self.AFC.gcode.respond_raw(logo)
                else:
                    self.AFC.gcode.respond_raw(logo_error)
            try:
                bypass = self.printer.lookup_object('filament_switch_sensor bypass').runout_helper
                if bypass.filament_present == True:
                    self.AFC.gcode.respond_info("Filament loaded in bypass, not doing toolchange")
            except: bypass = None

            for EXTRUDE in self.AFC.extruders.keys():
                CUR_EXTRUDER = self.printer.lookup_object('AFC_extruder ' + EXTRUDE)
                if CUR_EXTRUDER.tool_start_state == True and bypass != True:
                    if not self.AFC.extruders[EXTRUDE]['lane_loaded']:
                        self.AFC.gcode.respond_info("<span class=error--text>{} loaded with out identifying lane in AFC.vars.tool file<span>".format(EXTRUDE))

        # Defaulting to no active spool, putting at end so endpoint has time to register
        if self.AFC.current is None:
            self.AFC.SPOOL.set_active_spool( None )

def load_config(config):
    return afcPrep(config)

