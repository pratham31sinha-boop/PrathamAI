from datetime import date, datetime

# Standard ISO date format
print(date.today())

# Custom formatted date
print(datetime.now().strftime("%B %d, %Y"))
