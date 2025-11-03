# MARC_856_u-z_Encoder
Encodes URLs in .mrc files in 856 subfields U and Z

Package requirements: urllib.parse, csv, threading, pymarc, tkinter

What it does:
- Imports .mrc file
- Looks through MARC 856 $$u and $$z and looks to match URLs with /login
- Assumes that is an EZProxy URL
- Encodes the proxied URL
- Replaces /login?url=UTF8URL with /login?qurl=PERCENTENCODEDURL
- Outputs a new updated .mrc file
