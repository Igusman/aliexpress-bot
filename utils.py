import pyshorteners

def shorten_url(long_url):
    try:
        shortener = pyshorteners.Shortener()
        return shortener.tinyurl.short(long_url)
    except Exception as e:
        print("🔗 שגיאה בקיצור קישור:"[::-1], e)
        return long_url