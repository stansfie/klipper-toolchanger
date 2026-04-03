# Probe helper classes for klipper-toolchanger compatibility
# Extracted from Klipper's probe.py to avoid requiring Klipper update
#
# Copyright (C) 2017-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from . import manual_probe

HINT_TIMEOUT = """
If the probe did not move far enough to trigger, then
consider reducing the Z axis minimum position so the probe
can travel further (the Z minimum position can be negative).
"""

# Helper to read multi-sample parameters from config
class ProbeParameterHelper:
    def __init__(self, config):
        gcode = config.get_printer().lookup_object('gcode')
        self.dummy_gcode_cmd = gcode.create_gcode_command("", "", {})
        # Configurable probing speeds
        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.lift_speed = config.getfloat('lift_speed', self.speed, above=0.)
        # Multi-sample support (for improved accuracy)
        self.sample_count = config.getint('samples', 1, minval=1)
        self.sample_retract_dist = config.getfloat('sample_retract_dist', 2.,
                                                    above=0.)
        atypes = ['median', 'average']
        self.samples_result = config.getchoice('samples_result', atypes,
                                                'average')
        self.samples_tolerance = config.getfloat('samples_tolerance', 0.100,
                                                  minval=0.)
        self.samples_retries = config.getint('samples_tolerance_retries', 0,
                                              minval=0)
    def get_probe_params(self, gcmd=None):
        if gcmd is None:
            gcmd = self.dummy_gcode_cmd
        probe_speed = gcmd.get_float("PROBE_SPEED", self.speed, above=0.)
        lift_speed = gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.)
        samples = gcmd.get_int("SAMPLES", self.sample_count, minval=1)
        sample_retract_dist = gcmd.get_float("SAMPLE_RETRACT_DIST",
                                              self.sample_retract_dist, above=0.)
        samples_tolerance = gcmd.get_float("SAMPLES_TOLERANCE",
                                            self.samples_tolerance, minval=0.)
        samples_retries = gcmd.get_int("SAMPLES_TOLERANCE_RETRIES",
                                        self.samples_retries, minval=0)
        samples_result = gcmd.get("SAMPLES_RESULT", self.samples_result)
        return {'probe_speed': probe_speed,
                'lift_speed': lift_speed,
                'samples': samples,
                'sample_retract_dist': sample_retract_dist,
                'samples_tolerance': samples_tolerance,
                'samples_tolerance_retries': samples_retries,
                'samples_result': samples_result}

# Helper to read the xyz probe offsets from the config
class ProbeOffsetsHelper:
    def __init__(self, config):
        self.x_offset = config.getfloat('x_offset', 0.)
        self.y_offset = config.getfloat('y_offset', 0.)
        self.z_offset = config.getfloat('z_offset')
    def get_offsets(self, gcmd=None):
        return self.x_offset, self.y_offset, self.z_offset

# Homing via probe:z_virtual_endstop
class HomingViaProbeHelper:
    def __init__(self, config, mcu_probe, param_helper):
        self.printer = config.get_printer()
        self.mcu_probe = mcu_probe
        self.param_helper = param_helper
        self.multi_probe_pending = False
        # Infer Z position
        if config.has_section('stepper_z'):
            zconfig = config.getsection('stepper_z')
            self.z_min_position = zconfig.getfloat('position_min', 0.,
                                                    note_valid=False)
        else:
            pconfig = config.getsection('printer')
            self.z_min_position = pconfig.getfloat('minimum_z_position', 0.,
                                                    note_valid=False)
        self.results = []
        # Register event handlers
        self.printer.register_event_handler("gcode:command_error",
                                             self._handle_command_error)
    def _handle_command_error(self):
        if self.multi_probe_pending:
            self.multi_probe_pending = False
            try:
                self.mcu_probe.multi_probe_end()
            except:
                logging.exception("Homing multi-probe end")
    def start_probe_session(self, gcmd):
        self.mcu_probe.multi_probe_begin()
        self.results = []
        return self
    def run_probe(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        pos[2] = self.z_min_position
        speed = self.param_helper.get_probe_params(gcmd)['probe_speed']
        phoming = self.printer.lookup_object('homing')
        try:
            ppos = phoming.probing_move(self.mcu_probe, pos, speed)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        # Create result - handle both old and new Klipper API
        try:
            # Try new API (returns ProbeResult)
            res = manual_probe.create_probe_result(ppos, (0., 0., 0.))
        except:
            # Fall back to old API (returns list/tuple)
            res = ppos
        self.results.append(res)
    def pull_probed_results(self):
        res = self.results
        self.results = []
        return res
    def end_probe_session(self):
        self.results = []
        self.mcu_probe.multi_probe_end()

# Helper to track multiple probe attempts in a single command
class ProbeSessionHelper:
    def __init__(self, config, param_helper, start_session_cb):
        self.printer = config.get_printer()
        self.param_helper = param_helper
        self.start_session_cb = start_session_cb
        # Session state
        self.hw_probe_session = None
        self.results = []
        # Register event handlers
        self.printer.register_event_handler("gcode:command_error",
                                             self._handle_command_error)
    def _handle_command_error(self):
        if self.hw_probe_session is not None:
            try:
                self.end_probe_session()
            except:
                logging.exception("Multi-probe end")
    def _probe_state_error(self):
        raise self.printer.command_error(
            "Internal probe error - start/end probe session mismatch")
    def start_probe_session(self, gcmd):
        if self.hw_probe_session is not None:
            self._probe_state_error()
        self.hw_probe_session = self.start_session_cb(gcmd)
        self.results = []
        return self
    def end_probe_session(self):
        hw_probe_session = self.hw_probe_session
        if hw_probe_session is None:
            self._probe_state_error()
        self.results = []
        self.hw_probe_session = None
        hw_probe_session.end_probe_session()
    def _probe(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        curtime = self.printer.get_reactor().monotonic()
        if 'z' not in toolhead.get_status(curtime)['homed_axes']:
            raise self.printer.command_error("Must home before probe")
        try:
            self.hw_probe_session.run_probe(gcmd)
            epos = self.hw_probe_session.pull_probed_results()[0]
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        # Allow axis_twist_compensation to update results
        results = [epos]
        self.printer.send_event("probe:update_results", results)
        epos = results[0]
        # Report results - handle both old and new API
        gcode = self.printer.lookup_object('gcode')
        try:
            # Try new API (ProbeResult with bed_x, bed_y, bed_z)
            gcode.respond_info("probe: at %.3f,%.3f bed will contact at z=%.6f"
                               % (epos.bed_x, epos.bed_y, epos.bed_z))
        except:
            # Fall back to old API (list/tuple)
            gcode.respond_info("probe: at %.3f,%.3f bed will contact at z=%.6f"
                               % (epos[0], epos[1], epos[2]))
        return epos
    def run_probe(self, gcmd):
        if self.hw_probe_session is None:
            self._probe_state_error()
        params = self.param_helper.get_probe_params(gcmd)
        toolhead = self.printer.lookup_object('toolhead')
        probexy = toolhead.get_position()[:2]
        retries = 0
        positions = []
        sample_count = params['samples']
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(gcmd)
            positions.append(pos)
            # Check samples tolerance
            try:
                # Try new API
                z_positions = [p.bed_z for p in positions]
            except:
                # Fall back to old API
                z_positions = [p[2] for p in positions]
            if max(z_positions)-min(z_positions) > params['samples_tolerance']:
                if retries >= params['samples_tolerance_retries']:
                    raise gcmd.error("Probe samples exceed samples_tolerance")
                gcmd.respond_info("Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
            # Retract
            if len(positions) < sample_count:
                cur_z = toolhead.get_position()[2]
                toolhead.manual_move(
                    probexy + [cur_z + params['sample_retract_dist']],
                    params['lift_speed'])
        # Calculate result
        try:
            # Try importing calc function from probe module
            from . import probe
            epos = probe.calc_probe_z_average(positions, params['samples_result'])
        except:
            # Fall back to simple average
            if params['samples_result'] == 'median':
                positions_sorted = sorted(positions, key=lambda p: p[2] if isinstance(p, (list, tuple)) else p.bed_z)
                middle = len(positions_sorted) // 2
                if len(positions_sorted) % 2 == 1:
                    epos = positions_sorted[middle]
                else:
                    # Average the two middle values
                    try:
                        z1 = positions_sorted[middle-1].bed_z
                        z2 = positions_sorted[middle].bed_z
                        x1 = positions_sorted[middle-1].bed_x
                        y1 = positions_sorted[middle-1].bed_y
                        x2 = positions_sorted[middle].bed_x
                        y2 = positions_sorted[middle].bed_y
                        epos = manual_probe.ProbeResult((x1+x2)/2, (y1+y2)/2, (z1+z2)/2)
                    except:
                        epos = [(positions_sorted[middle-1][i] + positions_sorted[middle][i]) / 2 for i in range(3)]
            else:
                # Average
                inv_count = 1. / float(len(positions))
                try:
                    # Try new API
                    x = sum([p.bed_x for p in positions]) * inv_count
                    y = sum([p.bed_y for p in positions]) * inv_count
                    z = sum([p.bed_z for p in positions]) * inv_count
                    epos = manual_probe.ProbeResult(x, y, z)
                except:
                    # Fall back to old API
                    epos = [sum([p[i] for p in positions]) * inv_count for i in range(3)]
        self.results.append(epos)
    def pull_probed_results(self):
        res = self.results
        self.results = []
        return res

# Helper to implement common probing commands
class ProbeCommandHelper:
    def __init__(self, config, probe, query_endstop=None):
        self.printer = config.get_printer()
        self.probe = probe
        self.query_endstop = query_endstop
        self.name = config.get_name()
        # QUERY_PROBE command
        self.last_state = False
        self.last_z_result = 0.
    def get_status(self, eventtime):
        return {'name': self.name,
                'last_query': self.last_state,
                'last_z_result': self.last_z_result}
