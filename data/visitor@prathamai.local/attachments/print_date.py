from datetime import datetime

# Prints the current date in YYYY-MM-DD format
print(f"Current Date: {datetime.now().strftime('%Y-%m-%d')}")

# Prints formatted date with month name
print(f"Formatted Date: {datetime.now().strftime('%B %d, %Y')}")
