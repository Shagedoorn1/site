# -*- coding: utf-8 -*-
"""
This module contains classes for doing tomography experiments with the quEDU module.

2025 THUAS

Sven Hagedoorn <S.P.M.A.Hagedoorn@student.hhs.nl>

"""

import sys
import os
import time
import csv
import warnings
import ctypes as ct
import numpy as np
import pandas as pd
from collections import defaultdict

sys.path.append("quEDU_ED_Python")
from quEDU_DLL_Wrapper.quEDU_Hardware import quEDU_ED_Hardware

# ------------------- Globals -------------------
IP_ADDRESS = "192.168.0.1"

STEPS_PER_REV = 4800
DEG_TO_STEP = STEPS_PER_REV / 360.0

MOTOR_MAP = {
    # It is important that the motors are connected like this. 
    # If the quADD-ED is not connected like this, either change the numbers or change the physical configuration
    # Run with the --explain-setup flag to check and verify configuration.
    
    #Qubit 1
    "QWP1": 2,
    "Pol1": 3,
    #Qubit 2
    "QWP2": 1,
    "Pol2": 4
}

# ------------------- Hardware -------------------
quedu_ed_hardware = quEDU_ED_Hardware()

DATA_CALLBACK = ct.CFUNCTYPE(
    None, ct.c_int32, ct.c_int32, ct.c_int32,
    ct.POINTER(ct.c_int32), ct.POINTER(quedu_ed_hardware.qubase_hw_if.DYB_Meta)
)

# ------------------- Logic -------------------
class quEDU_Logic:
    def __init__(self):
        self.hardware = quedu_ed_hardware
        self.connected = False

        self.data_coinc = 8
        self.data_channel1 = 9
        self.data_channel2 = 10
        self.collector = None

    def connect_device(self, ip_address):
        err = self.hardware.connect_device(ip_address)
        if err == 0:
            self.connected = True
        else:
            raise RuntimeError(f"Failed to connect (error {err})")
        
    def disconnect_device(self):
        if self.hardware and self.connected :
            error_code = self.hardware.disconnect_device()
            if error_code == 0:
                self.connected = False

    def set_data_channel_callbacks(self):
        if self.collector is None:
            raise RuntimeError("Collector not assigned before setting callbacks")

        self.hardware.set_dataCallbackFunction(self.data_coinc, self.data_callback)
        self.hardware.set_dataCallbackFunction(self.data_channel1, self.data_callback)
        self.hardware.set_dataCallbackFunction(self.data_channel2, self.data_callback)

    @DATA_CALLBACK
    def data_callback(channel, count, index, data, meta):
        logic = LogicInstance
        if logic.collector is None or count < 1:
            return
        if channel == logic.data_channel1:
            logic.collector._current_ch1 = data[0]
        elif channel == logic.data_channel2:
            logic.collector._current_ch2 = data[0]
        elif channel == logic.data_coinc:
            logic.collector._current_coinc = data[0]
            
# ------------------- Base Qubit -------------------
class BaseQubit:
    projections = {
        # The quEDU doesn't want to distinguish between qwps and polarizers. The motor itself (as far as I know) is the same, but for a qwp rotated 90 degrees in the positive direction
        # So 90 degrees gets subtracted from the qwp angles. But, negative angles aren't allowed, the motors will time out,
        # So we do angle = 180 - |original_angle - 90|, leading to the angles as seen bellow.
        "H": {"qwp": 90,  "pol": 0},
        "V": {"qwp": 90,  "pol": 90},
        "P": {"qwp": 135, "pol": 45},
        "M": {"qwp": 135, "pol": 135},
        "R": {"qwp": 135, "pol": 90},
        "L": {"qwp": 135, "pol": 0},
    }
    
    positions = None
    required_components = None
    
    def __init__(self, logic, n_samples=100, wait_time=5.0):
        self.logic = logic
        self.n_samples = n_samples
        self.wait_time = wait_time
        self.data = defaultdict(lambda: self._empty_measurement_dict())
        self._current_ch1 = None
        self._current_ch2 = None
        self._current_coinc = None
        
    def _empty_measurement_dict(self):
        return {"ch1": [], "ch2": [], "coinc": []}
    
    def _angle_to_steps(self, angle):
        return round(angle * DEG_TO_STEP)
    
    def _move_motors_to_targets(self, motor_targets, timeout=None):
        if timeout is None:
            timeout = self.wait_time

        hw = self.logic.hardware

        # Step 1: Send all targets
        for motor_idx, steps in motor_targets.items():
            method = f"set_motor{motor_idx}_target_position" # Works with quEDU_ED_Python/
            if hasattr(hw, method):
                getattr(hw, method)(int(steps))
            elif hasattr(hw, "set_motor_target_position"):
                # Works with quEDU_Python/ in case anyone uses that, we can go on normally
                hw.set_motor_target_position(motor_idx - 1, int(steps)) # Motor index - 1 because quEDU_Python/ 0-indexes the motors
            else:
                raise RuntimeError(f"Cannot set motor {motor_idx}")

        # Step 2: Wait for completion
        start = time.time()
        done = {idx: False for idx in motor_targets}

        while not all(done.values()) and (time.time() - start) < timeout:
            for motor_idx, target in motor_targets.items():
                if done[motor_idx]:
                    continue
                try:
                    method = f"get_motor{motor_idx}_current_position"
                    if hasattr(hw, method):
                        pos = getattr(hw, method)()
                        if abs(pos - target) <= 1:
                            done[motor_idx] = True
                except:
                    pass
            time.sleep(0.05)

        # Step 3: Report final positions
        for motor_idx, target in motor_targets.items():
            try:
                method = f"get_motor{motor_idx}_current_position"
                if hasattr(hw, method):
                    final = getattr(hw, method)()
                    deg = final / DEG_TO_STEP
                    print(f"Motor {motor_idx} to {final} steps ({deg:.1f}°)")
            except:
                pass

        if not all(done.values()):
            warnings.warn("Some motors timed out")
            
    def run(self):
        total_positions = len(self.positions)
        estimated_seconds_per_position = self.n_samples * 0.1  # fallback

        print(f"Starting {self.__class__.__name__}")
        print(f"{total_positions} positions × {self.n_samples} samples "
              f"(≈ {estimated_seconds_per_position * total_positions / 60:.1f} minutes total)\n")

        start_time = time.time()
        position_start_time = start_time

        for idx, pos in enumerate(self.positions):
            position_start_time = time.time()  # reset at start of each position

            # === Smart & accurate ETA ===
            elapsed_total = time.time() - start_time
            positions_done = idx + 1

            if positions_done <= 3:
                avg_time_per_pos = estimated_seconds_per_position
            else:
                avg_time_per_pos = elapsed_total / positions_done

            # Time already spent in current position
            time_in_current = time.time() - position_start_time

            # Remaining full positions (after current one)
            remaining_full_positions = total_positions - positions_done

            remaining_in_current = avg_time_per_pos - time_in_current
            if remaining_in_current < 0:
                remaining_in_current = 0

            eta_seconds = int(remaining_full_positions * avg_time_per_pos + remaining_in_current)

            h = eta_seconds // 3600
            m = (eta_seconds % 3600) // 60
            s = eta_seconds % 60

            print(f"Measuring position {pos}, ({positions_done}/{total_positions}), "
                  f"time left: {h:01d}:{m:02d}:{s:02d}")

            # === Do the actual measurement ===
            self.measure_position(pos)

        # Final message
        total_time = int(time.time() - start_time)
        h = total_time // 3600
        m = (total_time % 3600) // 60
        s = total_time % 60
        print(f"\nTomography complete in {h:01d}:{m:02d}:{s:02d}!")
           
    
# ------------------- 2 Qubit -------------------
class DoubleQubit(BaseQubit):
    positions = [
        "HH","HV","VH","VV","PP","PM","MP","MM",
        "RR","RL","LR","LL","HP","HM","VP","VM",
        "HR","HL","VL","VR","PH","MH","PV","MV",
        "RH","LH","LV","RV","PR","PL","MR","ML",
        "RP","LP","RM","LM"
    ]
    required_components = {"QWP1", "Pol1", "QWP2", "Pol2"}

    def set_components(self, pos):
        q1, q2 = pos[0], pos[1]
        angles = {
            "QWP1": self.projections[q1]["qwp"],
            "Pol1":  self.projections[q1]["pol"],
            "QWP2": self.projections[q2]["qwp"],
            "Pol2":  self.projections[q2]["pol"],
        }
        targets = {MOTOR_MAP[c]: self._angle_to_steps(a) for c, a in angles.items()}
        self._move_motors_to_targets(targets)
        print(f"Motors set to {pos}: {angles}\n")


    def measure_position(self, pos_name):
        self.set_components(pos_name)
        for _ in range(self.n_samples):
            while self._current_ch1 is None or self._current_ch2 is None or self._current_coinc is None:
                time.sleep(0.01)
            self.data[pos_name]["ch1"].append(self._current_ch1)
            self.data[pos_name]["ch2"].append(self._current_ch2)
            self.data[pos_name]["coinc"].append(self._current_coinc)
            self._current_ch1 = None
            self._current_ch2 = None
            self._current_coinc = None
            time.sleep(0.05)

    def save_csv(self, filename="double_qubit_tomography.csv", n_sigma=2):
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Position","Q1","Q2","Avg_ch1","Avg_ch2","Avg_coinc", "Error_1", "Error_2", "Error_coinc",
                             "ch1","ch2","coinc"])
            for pos in self.positions:
                d = self.data[pos]
                avg1 = sum(d["ch1"])/len(d["ch1"]) if d["ch1"] else 0
                err1 = (n_sigma/np.sqrt(n_samples)) * np.std(d["ch1"], ddof = 1) if d["ch1"] else 0
                avg2 = sum(d["ch2"])/len(d["ch2"]) if d["ch2"] else 0
                err2 = (n_sigma/np.sqrt(n_samples)) * np.std(d["ch2"], ddof = 1) if d["ch2"] else 0
                avgc = sum(d["coinc"])/len(d["coinc"]) if d["coinc"] else 0
                errc = (n_sigma/np.sqrt(n_samples)) * np.std(d["coinc"], ddof = 1) if d["coinc"] else 0
                writer.writerow([pos, pos[0], pos[1], avg1, avg2, avgc, err1, err2,  errc,
                                 ";".join(map(str,d["ch1"])),
                                 ";".join(map(str,d["ch2"])),
                                 ";".join(map(str,d["coinc"]))])
        print(f"Saved to {filename}")
        
    def calc_results(self, filename):
        groups = {
            "HV": ["HH", "HV", "VH", "VV"],
            "PM": ["PP", "PM", "MP", "MM"],
            "RL": ["RR", "RL", "LR", "LL"],
            "HP": ["HP", "HM", "VP", "VM"],
            "HR": ["HR", "HL", "VR", "VL"],
            "PH": ["PH", "MH", "PV", "MV"],
            "RH": ["RH", "LH", "LV", "RV"],
            "PR": ["PR", "PL", "MR", "ML"],
            "RP": ["RP", "LP", "RM", "LM"],
        }
                
        df = pd.read_csv(filename)
                
        pos_to_coinc = {}
        for _, row in df.iterrows():
            pos = str(row["Position"]).strip()
            if pos in self.positions:
                val = row["Avg_coinc"]
                # handle strings or empty
                try:
                    pos_to_coinc[pos] = float(val)
                except Exception:
                    pos_to_coinc[pos] = 0.0
        
        # convenience function to access coincidences by name
        C = lambda name: pos_to_coinc.get(name, 0.0)
        
        freq = {}

        for _, outcomes in groups.items():
            for o in outcomes:
                if C(o) == 0:
                    warnings.warn("No coincidence for position {o}")
            den = sum(C(o) for o in outcomes)
            if den == 0:
                raise ValueError(
                    f"No total coincidence count for basis {outcomes}."
                )
            for o in outcomes:
                freq[o.lower()] = C(o) / den
        
        T00 = 1.0

        TZZ = freq["hh"] - freq["hv"] - freq["vh"] + freq["vv"]
        TXX = freq["pp"] - freq["pm"] - freq["mp"] + freq["mm"]
        TYY = freq["rr"] - freq["rl"] - freq["lr"] + freq["ll"]

        TZ0 = (1.0 / 3.0) * (
            (freq["hp"] + freq["hm"] - freq["vp"] - freq["vm"]) +
            (freq["hr"] + freq["hl"] - freq["vr"] - freq["vl"]) +
            (freq["hh"] + freq["hv"] - freq["vh"] - freq["vv"])
        )

        T0Z = (1.0 / 3.0) * (
            (freq["ph"] + freq["mh"] - freq["pv"] - freq["mv"]) +
            (freq["rh"] + freq["lh"] - freq["rv"] - freq["lv"]) +
            (freq["hh"] + freq["hv"] - freq["vh"] - freq["vv"])
        )

        TX0 = (1.0 / 3.0) * (
            (freq["pp"] + freq["pm"] - freq["mp"] - freq["mm"]) +
            (freq["pr"] + freq["pl"] - freq["mr"] - freq["ml"]) +
            (freq["ph"] + freq["pv"] - freq["mh"] - freq["mv"])
        )

        T0X = (1.0 / 3.0) * (
            (freq["pp"] + freq["pm"] - freq["mp"] - freq["mm"]) +
            (freq["rp"] + freq["lp"] - freq["rm"] - freq["lm"]) +
            (freq["hp"] + freq["vp"] - freq["hm"] - freq["vm"])
        )

        TY0 = (1.0 / 3.0) * (
            (freq["rp"] + freq["rm"] - freq["lp"] - freq["lm"]) +
            (freq["rr"] + freq["rl"] - freq["lr"] - freq["ll"]) +
            (freq["rh"] + freq["rv"] - freq["lh"] - freq["lv"])
        )

        T0Y = (1.0 / 3.0) * (
            (freq["pr"] + freq["mr"] - freq["pl"] - freq["ml"]) +
            (freq["rr"] + freq["lr"] - freq["rl"] - freq["ll"]) +
            (freq["hr"] + freq["vr"] - freq["hl"] - freq["vl"])
        )

        TXZ = freq["hp"] - freq["hm"] - freq["vp"] + freq["vm"]
        TZX = freq["ph"] - freq["mh"] - freq["pv"] + freq["mv"]

        TXY = freq["hr"] - freq["hl"] - freq["vr"] + freq["vl"]
        TYX = freq["rh"] - freq["lh"] - freq["rv"] + freq["lv"]

        TZY = freq["rh"] - freq["lh"] - freq["lv"] + freq["rv"]
        TYZ = freq["hr"] - freq["hl"] - freq["vl"] + freq["vr"]
        
        rho = (1.0/4.0) * np.array([
            [T00 + T0Z    + TZ0    + TZZ,     T0X - 1j*T0Y - TZX    - 1j*TZY,  TX0 + TXZ    - 1j*TY0 - 1j*TYZ,  TXX - 1j*TXY - 1j*TYX - TYY   ],
            [T0X + 1j*T0Y + TZX    + 1j*TZY,  T00 - T0Z    + TZ0    - TZZ,     TXX + 1j*TXY - 1j*TYX + TYY,     TX0 - TXZ    - 1j*TY0 + 1j*TYZ],
            [TX0 + TXZ    + 1j*TY0 + 1j*TYZ,  TXX - 1j*TXY + 1j*TYX + TYY,     T00 + T0Z    - TZ0    - TZZ,     T0X - 1j*T0Y - TZX    + 1j*TZY],
            [TXX + 1j*TXY + 1j*TYX - TYY,     TX0 - TXZ    + 1j*TY0 - 1j*TYX,  T0X + 1j*T0Y - TZX    - 1j*TZY,  T00 - T0Z    - TZ0    + TZZ   ]
        ], dtype=complex)
        
        herm_rho = rho.conj().T
        hermiticity = np.max(np.abs(rho - herm_rho))
        trace = np.trace(rho)
        purity = np.real(np.trace(rho @ rho))
        
        results = {
            "rho": rho,
            "hermiticity": hermiticity,
            "trace": trace,
            "purity": purity
        }
        return results
        
# ------------------- 1 Qubit -------------------
class SingleQubit(BaseQubit):
    positions = [
        "H", "V", "P", "M", "R", "L"
    ]
    required_components = {"QWP1", "Pol1"}

    def set_components(self, pos):
        q1 = pos[0]
        angles = {
            "QWP1": self.projections[q1]["qwp"],
            "Pol1":  self.projections[q1]["pol"],
        }
        targets = {MOTOR_MAP[c]: self._angle_to_steps(a) for c, a in angles.items()}
        self._move_motors_to_targets(targets)
        print(f"Motors set to {pos}: {angles}")


    def measure_position(self, pos_name):
        self.set_components(pos_name)
        for _ in range(self.n_samples):
            while self._current_ch1 is None:
                time.sleep(0.01)
            self.data[pos_name]["ch1"].append(self._current_ch1)
            self._current_ch2 = None
            time.sleep(0.05)

    def save_csv(self, filename="single_qubit_tomography.csv", n_sigma=2):
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Position","Q1","Avg_ch1", "Error_1", "ch1"])
            for pos in self.positions:
                d = self.data[pos]
                avg1 = sum(d["ch1"])/len(d["ch1"]) if d["ch1"] else 0
                err1 = (n_sigma/np.sqrt(n_samples)) * np.std(d["ch1"], ddof = 1) if d["ch1"] else 0
                writer.writerow([pos, pos[0],avg1, err1,
                                 ";".join(map(str,d["ch1"])),
                                 ])
        print(f"Saved to {filename}")
    
    def calc_results(self, filename, n_sigma=2):
        df = pd.read_csv(filename)
                
        pos_to_coinc = {}
        for _, row in df.iterrows():
            pos = str(row["Position"]).strip()
            if pos in self.positions:
                val = row["Avg_ch1"]
                # handle strings or empty
                try:
                    pos_to_coinc[pos] = float(val)
                except Exception:
                    pos_to_coinc[pos] = 0.0
        
        C = lambda name: pos_to_coinc.get(name, 0.0)
        
        # Pauli matrices
        s_0 = np.array([
            [1, 0],
            [0, 1]
        ])
        s_x = np.array([
            [0, 1],
            [1, 0]
        ])
        s_y = np.array([
            [1, -1j],
            [1j, 1]
        ], dtype="complex")
        s_z = np.array([
            [1, 0],
            [0, -1]
        ])
        
        T0 = 1
        
        TX = (C("P") - C("M"))/(C("P") + C("M"))
        TY = (C("R") - C("L"))/(C("R") + C("L"))
        TZ = (C("H") - C("V"))/(C("H") + C("V"))
        
        rho = (1/2) * (T0 * s_0 + TX * s_x + TY * s_y + TZ * s_z)
        
        herm_rho = rho.conj().T
        hermiticity = np.max(np.abs(rho - herm_rho))
        trace = np.trace(rho)
        purity = np.real(np.trace(rho @ rho))
        
        results = {
            "rho": rho,
            "hermiticity": hermiticity,
            "trace": trace,
            "purity": purity
        }
        return results

def cli_parse():
    tokens = {}
    for i in range(1, len(sys.argv)):
        token = sys.argv[i].split("=")
        if 0 <= 1 < len(token):
            tokens.update({
                token[0]: token[1]
            })
        else:
            tokens.update({
                token[0]: "NAN"
            })
    return tokens

# ------------------- Main -------------------
if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    name = "quEDU Tomography Experiments"
    n = len(name)
    # Behold; the power of VSCode:
    # GO! Unicode Insert! Use 'forms heavy' box drawing characters
    print("┏"+"━" * n + "┓")
    print("┃" + name + "┃")
    print("┗"+"━" * n + "┛\n")
    
    args = cli_parse()
    keys = list(args)

    #experiment variables, can be altered by CLI args.
    n_samples = 100
    wait_time = 5
    file_name = "tomography_counts.csv"
    n_sigma = 2
    qubits = 2
    online = True
    
    for i in range(len(args)):
        if keys[i] == "--n_samples" or keys[i] == "-n":
            n_samples = int(args[keys[i]])
        elif keys[i] == "--wait_time" or keys[i] == "-w":
            wait_time = int(args[keys[i]])
        elif keys[i] == "--out" or keys[i] == "-o":
            file_name = str(args[keys[i]]) + ".csv"
        elif keys[i] == "--n_sigma":
            n_sigma = int(args[keys[i]])
        elif keys[i] == "--qubits" or keys[i] == "-q":
            qubits = int(args[keys[i]])
        elif keys[i] == "--help" or keys[i] == "-h":
            print("Usage: python tom.py [arg]")
            print("Options: ")
            print("--n_samples, -n N (int):    Number of samples to take per setting.                                               Default: 100")
            print("--wait_time, -w N (int):    Max number of seconds to wait for the motors to reach position.                      Default: 5 seconds")
            print("--out,       -o Name (str): Name of the data output file. Do not include file extension (.csv).                  Default: tomography_counts")
            print("--n_sigma       N (int):    The ammount of standard deviations the error is calculated as.                       Default: 2")
            print("--qubits,    -q N (int):    Which experiment to do. 1 or 2 qubit tomography. The setup on the quADD is the same. Default: 2")
            print("--help,      -h:            Display this help message and exit")
            print("--offline:                  Run the script offline. The last data file, or one provided by the --out argument, will be analysed as set by --qubits argument")
            print("--explain-setup:            To check or verify that the quADD-ED is configured the same way the script assumes")
            os._exit(0)
        elif keys[i] == "--explain-setup":
            print("Set up or verify the quADD-ED like the script assumes. This is the same for the single and double qubit experiment.")
            print("The single qubit experiment only uses the left QWP, Polarizer and APD 2.\n")
            print("Prerequisite:")
            print("\tCopy the setup as seen in figure 2.4 of the quED-TOM manual V1.1 on page 14 (https://www.qutools.com/files/quED/quED-TOM_manual.pdf#page=14)")
            print("\tInstead of a quED with external qu3MD motor drivers this script uses a quEDU with a quADD-ED which has a 4-port motor driver built in.\n")
            print("How to connect:")
            print("\tNote: left and right are from the same perspective as in figure 2.4 (see link above).\n")
            print("\tConnect the right QWP to motor port 1 (far left)")
            print("\tConnect the left QWP to motor port 2")
            print("\tConnect the left Polarizer to motor port 3")
            print("\tConnect the right Polarizer to motor port 4 (far right)\n")
            print("\tConnect the right optic fiber to APD 1")
            print("\tConnect the left optic fiber to APD 2\n")
            os._exit(0)
        elif keys[i] == "--offline":
            online = False
        else:
            raise NotImplementedError(f"Argument {keys[i]} does not exist")
    
    print("Experiment variables:")
    print(f"\t- n_samples = {n_samples}")
    print(f"\t- wait_time = {wait_time}")
    print(f"\t- file_name = {file_name}")
    print(f"\t- n_sigma   = {n_sigma}")
    print(f"\t- qubits    = {qubits}")
    print(f"\t- online    = {online}")
    
    LogicInstance = quEDU_Logic()
    if online:
        LogicInstance.connect_device(ip_address=IP_ADDRESS)

    if qubits == 1:
        collector = SingleQubit(logic=LogicInstance, n_samples=n_samples, wait_time = wait_time)
    elif qubits == 2:
        collector = DoubleQubit(logic=LogicInstance, n_samples=n_samples, wait_time=wait_time)
    LogicInstance.collector = collector

    if online:
        LogicInstance.set_data_channel_callbacks()
        collector.run()
        collector.save_csv(file_name, n_sigma=n_sigma)
    results = collector.calc_results(filename=file_name)
    pd.set_option("display.precision", 6)
    for i in results.keys():
        if i == "rho":
            print(f"{i}:")
            print(pd.DataFrame(results[i]))
        else:
            print(f"{i} = {results[i]}")

    if online and LogicInstance.connected:
        LogicInstance.disconnect_device()