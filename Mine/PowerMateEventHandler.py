# requires python-evdev, python-requests
from evdev import InputDevice, categorize, ecodes, DeviceInfo, UInput, InputEvent, events
from select import select
from enum import Enum
import Queue
import os
import time
import threading

class ConsolidatedEventCodes(Enum):
    SINGLE_CLICK = 0
    DOUBLE_CLICK = SINGLE_CLICK + 1
    LONG_CLICK = DOUBLE_CLICK + 1
    RIGHT_TURN = LONG_CLICK + 1
    LEFT_TURN = RIGHT_TURN + 1

DEV_DIR = '/dev/input/'
delay = 100 # in milliseconds
long_press_time = .5 # time (in s) the button must be held to register a long press
time_down = 0 # time at which the button was last pressed down
led_brightness = 100
flash_duration = .2

max_devices = 16 # max number of input devices

button_pushed = 256
knob_turned = 7
positive = 1 # button down, or knob clockwise
negative = -1 # button up, or knob counter-clockwise


class PowerMateEventHandler:
    

    def __find_device(self):
        '''
        Finds and returns the device in /dev/input/event

        RETURN dev = An evdev.InputDevice. None if the device
        is not found.
        '''
        dev = None
        for dev in os.listdir(DEV_DIR):
            if dev.find("event") == 0:
                dev = InputDevice(DEV_DIR + dev)
                if dev.name.find('Griffin PowerMate') >= 0:
                    return dev


    def __init__(self):
        self.__raw_queue = Queue.Queue()
        self.__consolidated_queue = Queue.Queue()
        self.__dev = self.__find_device()

        uinput = UInput(events={ecodes.EV_MSC:[ecodes.MSC_PULSELED]})
        uinput.device = self.__dev
        uinput.fd = self.__dev.fd
        self.uinput = uinput

        self.__button_up = True
        self.__was_long = False


    def turn_off_led(self):
        '''
        Turns off the led in the base.
        '''
        self.uinput.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, 0)
        self.uinput.syn()



    def get_time_in_ms(self):
        return int(round(time.time() * 1000))


    def flash_led(self, num_flashes, brightness=led_brightness, duration=flash_duration):
        for i in range(num_flashes):
            self.uinput.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, brightness)
            self.uinput.syn()
            time.sleep(duration)
            self.uinput.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, 0)
            self.uinput.syn()
            time.sleep(.2)


    def __raw(self):
        while True:
            r,w,x = select([self.__dev], [], [])

            for event in self.__dev.read():
                self.__raw_queue.put(event)


    def __button_down(self, time_pressed):
        '''
        This function is intended to be run on its own thread,
        and is used to determine whether a button press was a normal/short
        press, or a long press.

        Once it registers a long press, it should flash the led on the device.

        PARAM time_pressed = int representing when the button was pressed
            Note that this is passed in rather than calculated here to
            account for any overhead spinning off the new thread.

        PARAM uinput = the PowerMat device

        Side Effects:
            LED is flashed
            was_long is set to True
       '''

        last_checked_at = self.get_time_in_ms()

        while not button_up:
            if last_checked_at - time_pressed > long_press_time:
                self.was_long = True
                self.flash_led(uinput, 1, led_brightness, flash_duration)
                return
            time.sleep(.01)
            last_checked_at = self.get_time_in_ms()
        return


    def __button_press(self, time_pressed):
        x = long_press_time
        check_time = time_pressed

        try:
            event = self.__raw_queue.get(timeout=x)
        except Queue.Empty:
            event = None
        x = x - ((self.get_time_in_ms() - check_time) / float(1000))

        while ((event == None) or (event.code != button_pushed)) and (x > 0):
            check_time = self.get_time_in_ms()
            try:
                event = self.__raw_queue.get(timeout=x)
            except Queue.Empty:
                event = None
            x = x - ((self.get_time_in_ms() - check_time) / float(1000))

        if x <= 0: # was long
            self.__consolidated_queue.put(ConsolidatedEventCodes.LONG_CLICK)
            # pull events until button is release (disallow turns while button is down)
            event = self.__raw_queue.get()
            while event.code != button_pushed:
                event = self.__raw_queue.get()

        else:
            # TODO handle double
            self.__consolidated_queue.put(ConsolidatedEventCodes.SINGLE_CLICK)
        return




    def __consolidated(self):

        time_of_last_turn = 0

        while True:
            event = self.__raw_queue.get()

            if event.code == knob_turned and self.get_time_in_ms() - delay > time_of_last_turn:
                if event.value > 0:
                    self.__consolidated_queue.put(ConsolidatedEventCodes.RIGHT_TURN)
                else:
                    self.__consolidated_queue.put(ConsolidatedEventCodes.LEFT_TURN)
                time_of_last_turn = self.get_time_in_ms()

            elif event.code == button_pushed:
                if event.value == positive: # button pressed
                    time_down = self.get_time_in_ms()
                    self.__button_press(time_down)


    def start(self):
        raw = threading.Thread(target = self.__raw)
        raw.daemon = True
        raw.start()

        cons = threading.Thread(target = self.__consolidated)
        cons.daemon = True
        cons.start()


    def get_next(self):
        return self.__consolidated_queue.get()


