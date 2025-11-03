#!/usr/bin/env python3

import os
import sys
import csv
import threading
from urllib.parse import urlparse, parse_qsl, urlencode, quote, unquote, urlunparse

try:
    from pymarc import MARCReader, MARCWriter
except Exception as e:
    import tkinter as _tk
    from tkinter import messagebox as _messagebox
    _root = _tk.Tk()
    _root.withdraw()
    _messagebox.showerror(
        "Missing dependency",
        f"pymarc is not installed.\n\nInstall with:\n  pip install pymarc\n\nError: {e}"
    )
    sys.exit(1)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "Fix EZproxy 856$u (GUI)"
DEFAULT_OUT_SUFFIX = "_fixed.mrc"
DEFAULT_CSV_SUFFIX = "_changes.csv"

def fix_ezproxy_url(u: str):

    try:
        parsed = urlparse(u)
    except Exception:
        return u, False

    if "/login" not in parsed.path or not parsed.query:
        return u, False

    params = parse_qsl(parsed.query, keep_blank_values=True)
    # Identify the first of url or qurl to use as the target
    target_val = None
    had_url = False
    had_qurl = False
    for k, v in params:
        if k == "url" and target_val is None:
            target_val = v
            had_url = True
        elif k == "qurl" and target_val is None:
            target_val = v
            had_qurl = True

    if target_val is None:
        return u, False

    # Build new param list without any existing url/qurl
    new_params = [(k, v) for (k, v) in params if k not in ("url", "qurl")]

    # Decode once so urlencode() will encode exactly once (prevents double-encoding)
    raw_target = unquote(target_val)
    new_params.append(("qurl", raw_target))

    # Reconstruct query using quote (not quote_plus) so spaces -> %20, not '+'
    new_query = urlencode(new_params, doseq=True, quote_via=quote)
    fixed = urlunparse(parsed._replace(query=new_query))

    changed = (fixed != u) or had_url  # changed if different OR we normalized url->qurl
    return fixed, changed


def process_file(infile, outfile, csv_path, log_fn):

    total = 0
    touched_recs = 0
    changed_links = 0
    rows = []

    log_fn(f"Reading: {infile}")
    try:
        with open(infile, 'rb') as fh, open(outfile, 'wb') as outfh:
            reader = MARCReader(fh, to_unicode=True, force_utf8=True, hide_utf8_warnings=True)
            writer = MARCWriter(outfh)

            for rec in reader:
                total += 1
                rec_changed = False
                rec_id = (rec['001'].value() if rec['001'] else "").strip()

                for f in rec.get_fields('856'):
                    subus = f.get_subfields('u')
                    if not subus:
                        continue

                    new_subus = []
                    sub_changed_any = False
                    for u in subus:
                        new_u, changed = fix_ezproxy_url(u)
                        new_subus.append(new_u)
                        if changed:
                            sub_changed_any = True
                            changed_links += 1
                            rows.append([rec_id, u, new_u])

                    if sub_changed_any:
                        # Remove all current $u then add back in original order
                        while 'u' in f:
                            f.delete_subfield('u')
                        for val in new_subus:
                            f.add_subfield('u', val)
                        rec_changed = True

                if rec_changed:
                    touched_recs += 1

                if total % 1000 == 0:
                    log_fn(f"Processed {total:,} records...")

            writer.close()

    except Exception as e:
        log_fn(f"❌ Error during processing: {e}")
        raise

    # Write CSV if requested and if there were changes
    if csv_path and rows:
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfh:
                w = csv.writer(csvfh)
                w.writerow(['record_001', 'original_856u', 'updated_856u'])
                w.writerows(rows)
        except Exception as e:
            log_fn(f"⚠️ Could not write CSV: {e}")
        else:
            log_fn(f"CSV change log written: {csv_path}")

    log_fn(f"✅ Done.\nRecords read: {total}\nRecords updated: {touched_recs}\n856$u links changed: {changed_links}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x520")
        self.minsize(640, 480)

        self.in_path = tk.StringVar()
        self.out_path = tk.StringVar()
        self.csv_path = tk.StringVar()

        self._build_ui()

    def _build_ui(self):
        pad = 10
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=pad, pady=pad)

        # Input
        ttk.Label(frm, text="Input .mrc file:").grid(row=0, column=0, sticky="w")
        in_entry = ttk.Entry(frm, textvariable=self.in_path)
        in_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Browse…", command=self.pick_input).grid(row=1, column=2, sticky="e", padx=(6, 0))

        # Output
        ttk.Label(frm, text="Output .mrc file:").grid(row=2, column=0, sticky="w")
        out_entry = ttk.Entry(frm, textvariable=self.out_path)
        out_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Browse…", command=self.pick_output).grid(row=3, column=2, sticky="e", padx=(6, 0))

        # CSV
        ttk.Label(frm, text="(Optional) CSV change log:").grid(row=4, column=0, sticky="w")
        csv_entry = ttk.Entry(frm, textvariable=self.csv_path)
        csv_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Browse…", command=self.pick_csv).grid(row=5, column=2, sticky="e", padx=(6, 0))

        # Run button + progress
        self.run_btn = ttk.Button(frm, text="Run", command=self.run_clicked)
        self.run_btn.grid(row=6, column=0, sticky="w", pady=(6, 6))

        self.pb = ttk.Progressbar(frm, mode="indeterminate")
        self.pb.grid(row=6, column=1, columnspan=2, sticky="ew", pady=(6, 6))

        # Log area
        ttk.Label(frm, text="Log:").grid(row=7, column=0, sticky="w")
        self.log = tk.Text(frm, height=14, wrap="word")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew")
        yscroll = ttk.Scrollbar(frm, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=8, column=3, sticky="ns")

        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=2)
        frm.columnconfigure(2, weight=0)
        frm.columnconfigure(3, weight=0)
        frm.rowconfigure(8, weight=1)

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="Select input MARC file",
            filetypes=[("MARC files", "*.mrc"), ("All files", "*.*")]
        )
        if path:
            self.in_path.set(path)
            base, _ = os.path.splitext(path)
            if not self.out_path.get():
                self.out_path.set(base + DEFAULT_OUT_SUFFIX)
            if not self.csv_path.get():
                self.csv_path.set(base + DEFAULT_CSV_SUFFIX)

    def pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Select output MARC file",
            defaultextension=".mrc",
            filetypes=[("MARC files", "*.mrc"), ("All files", "*.*")]
        )
        if path:
            self.out_path.set(path)

    def pick_csv(self):
        path = filedialog.asksaveasfilename(
            title="Select CSV change log (optional)",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if path:
            self.csv_path.set(path)

    def run_clicked(self):
        infile = self.in_path.get().strip()
        outfile = self.out_path.get().strip()
        csvfile = self.csv_path.get().strip() or None

        if not infile:
            messagebox.showwarning("Input required", "Please choose an input .mrc file.")
            return
        if not os.path.exists(infile):
            messagebox.showerror("File not found", f"Input file not found:\n{infile}")
            return

        if not outfile:
            messagebox.showwarning("Output required", "Please choose an output .mrc file.")
            return
        outdir = os.path.dirname(outfile) or "."
        if not os.path.isdir(outdir):
            messagebox.showerror("Invalid folder", f"Output folder does not exist:\n{outdir}")
            return
        if os.path.exists(outfile):
            if not messagebox.askyesno("Overwrite?", f"Output file exists:\n{outfile}\n\nOverwrite?"):
                return

        if csvfile:
            csvdir = os.path.dirname(csvfile) or "."
            if not os.path.isdir(csvdir):
                messagebox.showerror("Invalid folder", f"CSV folder does not exist:\n{csvdir}")
                return

        self.log_clear()
        self.log_append(f"Input:  {infile}")
        self.log_append(f"Output: {outfile}")
        if csvfile:
            self.log_append(f"CSV:    {csvfile}")
        self.log_append("Starting...\n")

        self.run_btn.config(state="disabled")
        self.pb.start(10)

        t = threading.Thread(target=self._run_worker, args=(infile, outfile, csvfile))
        t.daemon = True
        t.start()

    def _run_worker(self, infile, outfile, csvfile):
        try:
            process_file(infile, outfile, csvfile, self.log_append_threadsafe)
            self.log_append_threadsafe("\nAll done ✅")
        except Exception as e:
            self.log_append_threadsafe(f"\n❌ Failed: {e}")
        finally:
            self.after(0, lambda: (self.pb.stop(), self.run_btn.config(state="normal")))

    # ---------- Logging helpers ---------- #

    def log_append(self, text: str):
        self.log.insert("end", text + ("\n" if not text.endswith("\n") else ""))
        self.log.see("end")
        self.update_idletasks()

    def log_clear(self):
        self.log.delete("1.0", "end")

    def log_append_threadsafe(self, text: str):
        self.after(0, lambda: self.log_append(text))


if __name__ == "__main__":
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App()
    app.mainloop()
