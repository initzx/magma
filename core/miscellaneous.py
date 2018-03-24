import time


def format_time(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))
