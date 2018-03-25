import time


def format_time(millis):
    return time.strftime('%H:%M:%S', time.gmtime(millis/1000))
