import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import os
from firebase import Firebase
from objects import User
from scheduling import Computer
from datetime import datetime
from locks import acquire_shared_lock, acquire_exclusive_lock, release_lock
from fileops import safe_read, safe_write

class EditorApp:
    def __init__(self, root, firebase: Firebase = None, user: User = None):
        self.root = root
        self.firebase = firebase
        self.user = user
        root.title("CloudOS Editor")

        # Create main container
        main_container = ttk.PanedWindow(root, orient='horizontal')
        main_container.pack(expand=True, fill='both')

        # Left side: Cloud file browser
        left_frame = ttk.Frame(main_container)
        main_container.add(left_frame)

        # Cloud files treeview
        self.tree = ttk.Treeview(left_frame)
        self.tree.pack(expand=True, fill='both')
        self.tree.heading('#0', text='Cloud Files')
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)

        tree_buttons = ttk.Frame(left_frame)
        tree_buttons.pack(fill='x')
        ttk.Button(tree_buttons, text="Refresh", command=self.refresh_cloud_files).pack(side='left')
        ttk.Button(tree_buttons, text="Upload", command=self.upload_file_dialog).pack(side='left')
        ttk.Button(tree_buttons, text="Delete", command=self.delete_selected).pack(side='left')

        # Right side: Editor
        right_frame = ttk.Frame(main_container)
        main_container.add(right_frame)

        # Editor area
        self.text = tk.Text(right_frame, wrap='word')
        self.text.pack(expand=True, fill='both')

        toolbar = ttk.Frame(right_frame)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text="New", command=self.new_file_dialog).pack(side='left')
        ttk.Button(toolbar, text="Open Local", command=self.open_file_dialog).pack(side='left')
        self.save_btn = ttk.Button(toolbar, text="Save", command=self.save, state='disabled')
        self.save_btn.pack(side='left')
        ttk.Button(toolbar, text="Close", command=self.close_file).pack(side='left')
        self.progress = ttk.Progressbar(toolbar, mode='indeterminate', length=100)
        self.progress.pack(side='right', padx=5)
        self.status = ttk.Label(toolbar, text="Ready")
        self.status.pack(side='right')

        self.current_path = None
        self.current_cloud_path = None
        self.lock = None
        self.edit_mode = False
        self.is_cloud_file = False

        # Ensure cache path exists
        cache_path = os.environ.get('CACHE_PATH', './file_cache')
        os.makedirs(cache_path, exist_ok=True)
        os.makedirs(os.path.join(cache_path, 'meta'), exist_ok=True)

        # Initialize cloud file tree
        if self.firebase and self.user:
            self.refresh_cloud_files()

    def open_file_dialog(self):
        # Close current file if open
        if self.current_path:
            self._close_current_file()
            
        # Set initial directory to the CloudOS workspace
        initial_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Open File",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*")
            ]
        )
        if not path:
            return
            
        # Check if file is outside workspace and warn
        if not path.startswith(initial_dir):
            if not messagebox.askyesno(
                "Outside Workspace Warning",
                "This file is outside the CloudOS workspace. "
                "Some features may not work correctly.\n\n"
                "Would you like to make a copy in the workspace first?"
            ):
                # ask read or edit
                mode = messagebox.askquestion("Mode", "Open in edit mode? (No = read-only)", icon='question')
                self.edit_mode = (mode == 'yes')
                t = threading.Thread(target=self._open_file, args=(path,), daemon=True)
                t.start()
            else:
                # Copy to workspace first
                try:
                    new_path = os.path.join(initial_dir, os.path.basename(path))
                    with open(path, 'r', encoding='utf-8') as src:
                        content = src.read()
                    with open(new_path, 'w', encoding='utf-8') as dst:
                        dst.write(content)
                    path = new_path
                    messagebox.showinfo("Copy Complete", 
                        f"File copied to workspace as:\n{os.path.basename(path)}")
                    
                    # Now open the workspace copy
                    mode = messagebox.askquestion("Mode", "Open in edit mode? (No = read-only)", icon='question')
                    self.edit_mode = (mode == 'yes')
                    t = threading.Thread(target=self._open_file, args=(path,), daemon=True)
                    t.start()
                except Exception as e:
                    messagebox.showerror("Copy Failed", f"Could not copy file: {e}")

    def new_file_dialog(self):
        """Create a new text file"""
        # Close current file if open
        if self.current_path:
            self._close_current_file()
            
        # Set initial directory to the CloudOS workspace
        initial_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            title="Create New File",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*")
            ]
        )
        if not path:
            return
        
        # Create the new file and open it in edit mode
        self.edit_mode = True
        self.is_cloud_file = False
        self.current_cloud_path = None
        t = threading.Thread(target=self._open_file, args=(path,), daemon=True)
        t.start()

    def _close_current_file(self):
        """Close the currently open file, releasing locks"""
        if self.lock:
            try:
                release_lock(self.lock)
            except Exception:
                pass
            self.lock = None
        self.current_path = None
        self.current_cloud_path = None
        self.is_cloud_file = False
        self.text.delete('1.0', tk.END)
        self.text.config(state='normal')
        self.save_btn.config(state='disabled')

    def _open_file(self, path):
        try:
            # Close current file if one is open
            if self.current_path:
                self._close_current_file()
            
            self._set_status(f"Acquiring {'exclusive' if self.edit_mode else 'shared'} lock...")
            self.progress.start()

            # Ensure file permissions are correct before proceeding
            from fileops import set_windows_permissions
            parent = os.path.dirname(path) or '.'
            if parent:
                os.makedirs(parent, exist_ok=True)
                if not os.access(parent, os.R_OK) or (self.edit_mode and not os.access(parent, os.W_OK)):
                    set_windows_permissions(parent)
            
            # Create the file if it doesn't exist in edit mode
            if self.edit_mode and not os.path.exists(path):
                try:
                    with open(path, 'a') as f:
                        pass
                    set_windows_permissions(path)
                    if not (os.access(path, os.R_OK) and os.access(path, os.W_OK)):
                        raise PermissionError("Failed to set proper file permissions")
                except Exception as e:
                    raise PermissionError(f"Cannot create file with proper permissions: {e}")
            elif os.path.exists(path):
                # Fix permissions for existing file
                if not os.access(path, os.R_OK) or (self.edit_mode and not os.access(path, os.W_OK)):
                    set_windows_permissions(path)
                    if not os.access(path, os.R_OK) or (self.edit_mode and not os.access(path, os.W_OK)):
                        raise PermissionError(f"Cannot set proper permissions on existing file: {path}")

            # Read file content FIRST (before acquiring lock)
            # This prevents portalocker from blocking the read operation
            # For new files, content is empty
            content = ""
            if os.path.exists(path):
                try:
                    content = safe_read(path)
                except PermissionError as e:
                    # Try one more time to fix permissions
                    try:
                        set_windows_permissions(path)
                        content = safe_read(path)
                    except Exception as e2:
                        self.progress.stop()
                        self.root.after(0, lambda: messagebox.showerror("Permission Error", 
                            f"Could not read file due to permissions:\n{str(e)}\n\nTried to fix but: {str(e2)}"))
                        return
                except Exception as e:
                    self.progress.stop()
                    self.root.after(0, lambda: messagebox.showerror("Read Error", f"Could not read file: {e}"))
                    return

            # Now acquire the lock AFTER reading (to prevent others from modifying while editing)
            try:
                if self.edit_mode:
                    self.lock = acquire_exclusive_lock(path, timeout=10)
                else:
                    self.lock = acquire_shared_lock(path, timeout=10)
            except TimeoutError:
                if messagebox.askyesno("Lock Timeout", 
                    "File is locked by another process.\nWould you like to force unlock it?"):
                    # Force unlock by removing the lock file from temp directory
                    from locks import get_lock_path
                    lockfile = get_lock_path(path)
                    if os.path.exists(lockfile):
                        try:
                            os.remove(lockfile)
                            # Retry the lock
                            if self.edit_mode:
                                self.lock = acquire_exclusive_lock(path, timeout=5)
                            else:
                                self.lock = acquire_shared_lock(path, timeout=5)
                        except Exception as e:
                            raise Exception(f"Could not force unlock: {str(e)}")
                else:
                    raise
        except Exception as e:
            self._set_status("Access failed")
            messagebox.showerror("Access Error", str(e))
            self.progress.stop()
            return

        # Stop progress and update UI on main thread
        self.progress.stop()
        self.root.after(0, self._populate_editor, path, content)

    def _populate_editor(self, path, content):
        self.current_path = path
        self.text.delete('1.0', tk.END)
        self.text.insert(tk.END, content)
        if self.edit_mode:
            self.text.config(state='normal')
            self.save_btn.config(state='normal')
        else:
            self.text.config(state='disabled')
            self.save_btn.config(state='disabled')
        self._set_status(f"Opened {os.path.basename(path)} in {'edit' if self.edit_mode else 'read'} mode")

    def save(self):
        if not self.current_path:
            return
        data = self.text.get('1.0', tk.END)
        self.save_btn.config(state='disabled')
        self._set_status("Saving...")
        self.progress.start()
        t = threading.Thread(target=self._save_file, args=(self.current_path, data), daemon=True)
        t.start()

    def _save_file(self, path, data):
        try:
            # If we have an exclusive lock with portalocker, temporarily release it for writing
            lock_was_held = False
            if self.lock and self.lock.exclusive and hasattr(self.lock, '_fh') and self.lock._fh:
                lock_was_held = True
                # Temporarily release the lock
                release_lock(self.lock)
                self.lock = None
            
            # Write the file
            safe_write(path, data)
            
            # Don't re-acquire lock yet if we need to upload (upload needs file access)
            # We'll re-acquire after upload completes
            if self.is_cloud_file and self.firebase and self.user:
                if self.current_cloud_path:
                    # update_file signature: update_file(user, cloud_path, file_path)
                    cloud_path = self.current_cloud_path
                    # Upload while file is unlocked
                    self.firebase.update_file(self.user, cloud_path, path)
                else:
                    # New cloud file - upload_file signature: upload_file(user, cloud_path, file_path)
                    filename = os.path.basename(path)
                    cloud_path = f"documents/{filename}"
                    # Upload while file is unlocked
                    self.firebase.upload_file(self.user, cloud_path, path)
                self.refresh_cloud_files()
                
                # Now re-acquire the lock after upload completes
                if lock_was_held:
                    self.lock = acquire_exclusive_lock(path, timeout=10)
            else:
                # Not a cloud file, re-acquire lock immediately
                if lock_was_held:
                    self.lock = acquire_exclusive_lock(path, timeout=10)
            
            self._set_status("Saved")
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Save error", str(e)))
            self._set_status("Save failed")
            # Try to re-acquire lock on error
            if lock_was_held and not self.lock:
                try:
                    self.lock = acquire_exclusive_lock(path, timeout=5)
                except:
                    pass
        finally:
            self.root.after(0, lambda: [
                self.save_btn.config(state='normal'),
                self.progress.stop()
            ])

    def close_file(self):
        """Close the current file (public method for Close button)"""
        self._close_current_file()
        self._set_status("Ready")

    def _set_status(self, text):
        self.root.after(0, lambda: self.status.config(text=text))

    def refresh_cloud_files(self):
        """Refresh the cloud files tree view"""
        if not self.firebase or not self.user:
            return
        
        self.tree.delete(*self.tree.get_children())
        files = self.firebase.get_owned_files(self.user)
        # get_owned_files returns the owned_files dict directly, not wrapped
        root = files if files else {}
        
        def add_items(parent, items):
            for key, value in items.items():
                key = key.replace("&123", ".")
                if isinstance(value, dict) and 'type' not in value:
                    # Directory
                    folder = self.tree.insert(parent, 'end', text=key, open=False)
                    add_items(folder, value)
                else:
                    # File
                    self.tree.insert(parent, 'end', text=key, values=('file',))
        
        add_items('', root)

    def on_tree_select(self, event):
        """Handle cloud file selection"""
        selected = self.tree.selection()
        if not selected:
            return
        
        item = selected[0]
        path = []
        while item:
            path.insert(0, self.tree.item(item)['text'])
            item = self.tree.parent(item)
        
        # Treeview returns values as a list, check if 'file' is in the values
        item_values = self.tree.item(selected[0])['values']
        if item_values and 'file' in item_values:
            self._open_cloud_file('/'.join(path))

    def _open_cloud_file(self, cloud_path):
        """Open a cloud file"""
        if not self.firebase or not self.user:
            return

        # Close current file if open
        if self.current_path:
            self._close_current_file()

        mode = messagebox.askquestion("Mode", "Open in edit mode? (No = read-only)", icon='question')
        self.edit_mode = (mode == 'yes')
        
        self._set_status(f"Loading {os.path.basename(cloud_path)}...")
        self.progress.start()
        
        t = threading.Thread(target=self._load_cloud_file, args=(cloud_path,), daemon=True)
        t.start()

    def _load_cloud_file(self, cloud_path):
        """Background thread to load cloud file"""
        try:
            # get_file expects the full cloud_path, not just filename
            # cloud_path is like "documents/gagaga.txt"
            cached_path = self.firebase.get_file(self.user, cloud_path)
            if not cached_path:
                raise Exception("File not found in cloud storage")
            
            self.current_cloud_path = cloud_path
            self.is_cloud_file = True
            
            # Now open the cached file with proper locking
            self._open_file(cached_path)
        except Exception as e:
            self.root.after(0, lambda: [
                messagebox.showerror("Cloud Error", str(e)),
                self._set_status("Failed to load cloud file"),
                self.progress.stop()
            ])

    def upload_file_dialog(self):
        """Upload a new file to the cloud"""
        if not self.firebase or not self.user:
            return
            
        path = filedialog.askopenfilename()
        if not path:
            return
            
        filename = os.path.basename(path)
        self._set_status(f"Uploading {filename}...")
        self.progress.start()
        
        t = threading.Thread(target=self._upload_file, args=(path,), daemon=True)
        t.start()

    def _upload_file(self, local_path):
        """Background thread to upload file"""
        try:
            filename = os.path.basename(local_path)
            # upload_file signature: upload_file(user, cloud_path, file_path)
            # cloud_path is where it goes in cloud, file_path is local file path
            cloud_path = f"documents/{filename}"
            
            # Start upload (runs in background thread, so GUI stays responsive)
            self.firebase.upload_file(self.user, cloud_path, local_path)
            
            self.root.after(0, lambda: [
                self._set_status(f"Uploaded {filename}"),
                self.refresh_cloud_files()
            ])
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Upload Error", str(e)))
        finally:
            self.root.after(0, self.progress.stop)

    def delete_selected(self):
        """Delete selected cloud file"""
        if not self.firebase or not self.user:
            return
            
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Delete Error", "Please select a file to delete")
            return
            
        item = selected[0]
        # Check if it's a file - folders have empty values [], files have ['file']
        # Treeview returns values as a list, not tuple
        item_values = self.tree.item(item)['values']
        if not item_values or 'file' not in item_values:
            messagebox.showwarning("Delete Error", "Can only delete files, not folders")
            return
            
        if not messagebox.askyesno("Confirm Delete", 
                                  f"Delete {self.tree.item(item)['text']}?"):
            return
            
        # Build the full cloud path
        path = []
        current_item = item
        while current_item:
            path.insert(0, self.tree.item(current_item)['text'])
            current_item = self.tree.parent(current_item)
            
        cloud_path = '/'.join(path)
        self._set_status(f"Deleting {os.path.basename(cloud_path)}...")
        self.progress.start()
        
        t = threading.Thread(target=self._delete_file, args=(cloud_path,), daemon=True)
        t.start()

    def _delete_file(self, cloud_path):
        """Background thread to delete cloud file"""
        try:
            filename = os.path.basename(cloud_path)
            # delete_owned_file signature: delete_owned_file(user, cloud_path)
            # cloud_path should be the full path like "documents/filename.txt"
            self.firebase.delete_owned_file(self.user, cloud_path)
            self.root.after(0, lambda: [
                self._set_status(f"Deleted {filename}"),
                self.refresh_cloud_files()
            ])
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Delete Error", str(e)))
        finally:
            self.root.after(0, self.progress.stop)

if __name__ == '__main__':
    from firebase import Firebase
    from objects import User
    from scheduling import Computer
    import os
    from dotenv import load_dotenv
    
    # Setup like in main.py
    load_dotenv()
    computer = Computer()
    thread = threading.Thread(target=computer.run, daemon=True)
    thread.start()

    fb = Firebase(computer)
    # Replace with your credentials
    user = fb.login("johnlloydunida0@gmail.com", "password")
    
    root = tk.Tk()
    app = EditorApp(root, firebase=fb, user=user)
    root.geometry("1024x768")
    root.mainloop()