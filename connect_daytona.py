#!/usr/bin/env python3
"""
Pratham AI - Daytona Cloud Terminal Connector
Connects to Daytona using your API token, creates a cloud sandbox with all repository files,
and attaches the terminal remotely.
"""
import os
import sys

def main():
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key and len(sys.argv) > 1:
        api_key = sys.argv[1].strip()

    if not api_key:
        print("=" * 60)
        print("❌ Daytona API Token is required!")
        print("=" * 60)
        print("1. Get your token from: https://app.daytona.io/dashboard/keys")
        print("2. Run with your token:")
        print("   python3 connect_daytona.py <YOUR_DAYTONA_API_TOKEN>")
        print("   OR")
        print("   export DAYTONA_API_KEY='<YOUR_DAYTONA_API_TOKEN>'")
        print("   python3 connect_daytona.py")
        print("=" * 60)
        sys.exit(1)

    print("🚀 1/3 Authenticating with Daytona token...")
    exit_code = os.system(f"daytona login --api-key='{api_key}'")
    if exit_code != 0:
        print("⚠️ Warning: daytona login exited with non-zero code. Trying to proceed...")

    print("📦 2/3 Creating cloud sandbox and cloning repository...")
    os.system("daytona create https://github.com/pratham31sinha-boop/PrathamAI.git")

    print("💻 3/3 Connecting to Daytona terminal...")
    os.system("daytona ssh")

if __name__ == "__main__":
    main()
