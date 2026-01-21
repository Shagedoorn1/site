# -*- coding: utf-8 -*-
"""
This module contains classes for doing base experiments with the quEDU module.
Such as measuring dark counts

2025 THUAS

Sven Hagedoorn <S.P.M.A.Hagedoorn@student.hhs.nl>

"""

import sys
import os
import time
import csv
import keyboard
import ctypes as ct
import numpy as np
import pandas as pd
from collections import defaultdict

sys.path.append("quEDU_ED_Python")
from quEDU_DLL_Wrapper.quEDU_Hardware import quEDU_ED_Hardware

# ------------------- Globals -------------------
IP_ADDRESS = "192.168.0.1"

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


        self.data_channel1 = 9
        self.data_channel2 = 10
        self.data_channel3 = 12
        self.data_channel4 = 13
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
        
        self.hardware.set_dataCallbackFunction(self.data_channel1, self.data_callback)
        self.hardware.set_dataCallbackFunction(self.data_channel2, self.data_callback)
        self.hardware.set_dataCallbackFunction(self.data_channel3, self.data_callback)
        self.hardware.set_dataCallbackFunction(self.data_channel4, self.data_callback)
        
    @DATA_CALLBACK
    def data_callback(channel, count, index, data, meta):
        logic = LogicInstance
        if logic.collector is None or count < 1:
            return
        if channel == logic.data_channel1:
            logic.collector._current_ch1 = data[0]
        elif channel == logic.data_channel2:
            logic.collector._current_ch2 = data[0]
        elif channel == logic.data_channel3:
            logic.collector._current_ch3 = data[0]
        elif channel == logic.data_channel4:
            logic.collector._current_ch4 = data[0]
            
# ------------------- Base HBT -------------------
class BASE:
    def __init__(self, logic, n_samples=100):
        self.logic = logic
        self.n_samples = n_samples
        self.data = defaultdict(lambda: {"ch1": [], "ch2": [], "ch3": [], "ch4": [], "coinc12": [], "coinc13": [], "coinc14": [], "coinc23": [], "coinc24": [], "coinc34": []})
        self._current_ch1 = None
        self._current_ch2 = None
        self._current_ch3 = None
        self._current_ch4 = None
    
    def measure(self, pos_name="BASE"):
        while self._current_ch1 is None or self._current_ch2 is None or self._current_ch3 is None or self._current_ch4 is None:
            time.sleep(0.01)
        self.data[pos_name]["ch1"].append(self._current_ch1)
        self.data[pos_name]["ch2"].append(self._current_ch2)
        self.data[pos_name]["ch3"].append(self._current_ch3)
        self.data[pos_name]["ch4"].append(self._current_ch4)
        self._current_ch1 = None
        self._current_ch2 = None
        self._current_ch3 = None
        self._current_ch4 = None
        time.sleep(0.1)

    def run(self):
        print(f"Starting Base measurement: {self.n_samples} samples")
        print(f"≈ {(self.n_samples * 0.1) / 60:.1f} minutes total (including delays)\n")
        
        start_time = time.time()
        
        for i in range(self.n_samples):
            # === Smart ETA ===
            elapsed = time.time() - start_time
            samples_done = i + 1
            avg_time_per_sample = elapsed / samples_done if samples_done > 0 else 1.1  # estimate ~1.1s per sample
            remaining_samples = self.n_samples - samples_done
            eta_seconds = int(remaining_samples * avg_time_per_sample)
            
            h = eta_seconds // 3600
            m = (eta_seconds % 3600) // 60
            s = eta_seconds % 60
            
            print(f"Sample {samples_done}/{self.n_samples}, time left: {h:01d}:{m:02d}:{s:02d}")
            self.measure("BASE")

        total_time = int(time.time() - start_time)
        h = total_time // 3600
        m = (total_time % 3600) // 60
        s = total_time % 60
        print(f"\nBase measurement complete in {h:01d}:{m:02d}:{s:02d}!")
        self.save_csv()

    def save_csv(self, filename="base_data.csv", n_sigma=2):
        d = self.data["BASE"]  # your pos_name

        # Averages & errors
        avg_ch1 = np.mean(d["ch1"]) if d["ch1"] else 0
        err_ch1 = (n_sigma / np.sqrt(self.n_samples)) * np.std(d["ch1"], ddof=1) if d["ch1"] else 0

        avg_ch2 = np.mean(d["ch2"]) if d["ch2"] else 0
        err_ch2 = (n_sigma / np.sqrt(self.n_samples)) * np.std(d["ch2"], ddof=1) if d["ch2"] else 0

        avg_ch3 = np.mean(d["ch3"]) if d["ch3"] else 0
        err_ch3 = (n_sigma / np.sqrt(self.n_samples)) * np.std(d["ch3"], ddof=1) if d["ch3"] else 0

        avg_ch4 = np.mean(d["ch4"]) if d["ch4"] else 0
        err_ch4 = (n_sigma / np.sqrt(self.n_samples)) * np.std(d["ch4"], ddof=1) if d["ch4"] else 0

        # Write averages + errors
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Avg_ch1", "Err_ch1",
                "Avg_ch2", "Err_ch2",
                "Avg_ch3", "Err_ch3",
                "Avg_ch4", "Err_ch4",
            ])
            writer.writerow([
                avg_ch1, err_ch1,
                avg_ch2, err_ch2,
                avg_ch3, err_ch3,
                avg_ch4, err_ch4,
            ])

            # Raw data header
            writer.writerow([])
            writer.writerow(["Sample", "ch1", "ch2", "ch3", "ch4"])
            for i in range(self.n_samples):
                writer.writerow([
                    i+1,
                    d["ch1"][i] if i < len(d["ch1"]) else "",
                    d["ch2"][i] if i < len(d["ch2"]) else "",
                    d["ch3"][i] if i < len(d["ch3"]) else "",
                    d["ch4"][i] if i < len(d["ch4"]) else "",
                ])
        print(f"\nSaved to {filename}")

if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    name = "quEDU Base Experiments"
    n = len(name)
    print("┏" + "━" * n + "┓")
    print("┃" + name + "┃")
    print("┗" + "━" * n + "┛\n")

    filename = "hbt_data.csv"
    
    LogicInstance = quEDU_Logic()
    LogicInstance.connect_device(IP_ADDRESS)
    
    collector = BASE(LogicInstance, n_samples=10)
    LogicInstance.collector = collector
    
    LogicInstance.set_data_channel_callbacks()
    
    collector.run()
    
    if LogicInstance.connected:
        LogicInstance.disconnect_device()