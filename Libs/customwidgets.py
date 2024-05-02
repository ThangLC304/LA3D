import tkinter
import tkinter.ttk as ttk
import customtkinter
import json
import os
from PIL import Image, ImageTk
from pathlib import Path
import shutil
import cv2

from . import HISTORY_PATH, TEMPLATE_PATH
from Libs.misc import calculate_distance, get_static_dir, get_first_frame
from Libs.general import ParamsCalculator

import logging

logger = logging.getLogger(__name__)


############################################### TOOL TIP CLASS ################################################
class ToolTip(object):

    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0

    def showtip(self, text):
        "Display text in tooltip window"
        self.text = text
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 57
        y = y + cy + self.widget.winfo_rooty() +27
        self.tipwindow = tw = tkinter.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry("+%d+%d" % (x, y))
        label = tkinter.Label(tw, text=self.text, justify=tkinter.LEFT,
                      background="#ffffe0", relief=tkinter.SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

def CreateToolTip(widget, text):
    toolTip = ToolTip(widget)
    def enter(event):
        toolTip.showtip(text)
    def leave(event):
        toolTip.hidetip()
    widget.bind('<Enter>', enter)
    widget.bind('<Leave>', leave)

############################################### CUSTOM PROGRESS WINDOW CLASS ################################################

class ProgressWindow(tkinter.Toplevel):
        
    def __init__(self, master, title="Analysis Progress", geometry="300x250"):
        tkinter.Toplevel.__init__(self, master)
        self.title(title)
        self.geometry(geometry)

        FONT = ('Helvetica', 14, 'bold')

        self.group_label = tkinter.Label(self, text="Group Progress", font=FONT)
        self.group_label.pack(pady=5)
        self.group = ttk.Progressbar(self, length=100, mode='determinate')
        self.group.pack(pady=5)

        self.step_label = tkinter.Label(self, text="Step Progress", font=FONT)
        self.step_label.pack(pady=5)
        self.step = ttk.Progressbar(self, length=100, mode='determinate')
        self.step.pack(pady=5)

        self.task_label = tkinter.Label(self, text="Task Progress", font=FONT)
        self.task_label.pack(pady=5)
        self.task = ttk.Progressbar(self, length=100, mode='determinate')
        self.task.pack(pady=5)

    def group_update(self, value, text="Group Progress"):
        self.group_label["text"] = text
        self.group["value"] = value
        self.update()

    def step_update(self, value, text="Step Progress"):
        self.step_label["text"] = text
        self.step["value"] = value
        self.update()

    def task_update(self, value, text="Task Progress"):
        self.task_label["text"] = text
        self.task["value"] = value
        self.update()


############################################### CUSTOM DIALOG CLASS ################################################
class CustomDialog(tkinter.Toplevel):
    def __init__(self, master, title=None, message=None, button_text=None, button_command=None):
        tkinter.Toplevel.__init__(self, master)
        self.title(title)

        FONT=('Helvetica', 14, 'bold')

        self.label = tkinter.Label(self, text=message, font=FONT)
        self.label.pack(padx=10, pady=10)

        self.button_command = button_command
        self.button = tkinter.Button(self, text=button_text, command=self.ok)
        self.button.pack(pady=10)

        self.geometry("+%d+%d" % (master.winfo_rootx(), master.winfo_rooty()))

    def ok(self):
        if self.button_command is not None:
            self.button_command()
        self.destroy()

############################################### MEASURER CLASS ################################################

class RefFrameSelector(tkinter.Toplevel):
    def __init__(self, video_path, parent=None):
        super().__init__(parent)

        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path)
        self.current_frame = None
        self.returned_image = None

        self.init_ui()

    def init_ui(self):
        # Video Frame
        self.video_frame = tkinter.Label(self)
        self.video_frame.pack()

        # Slider
        self.slider = tkinter.Scale(self, from_=0, to=int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)), orient=tkinter.HORIZONTAL, command=self.update_frame)
        self.slider.pack()

        # Buttons
        use_frame_button = tkinter.Button(self, text="Use current selected frame", command=self.use_frame)
        use_frame_button.pack()

        cancel_button = tkinter.Button(self, text="Cancel", command=self.cancel)
        cancel_button.pack()

    def update_frame(self, value):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(value))
        ret, frame = self.cap.read()
        if ret:
            self.current_frame = frame
            self.show_frame()

    def show_frame(self):
        cv_image = cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(cv_image)
        tk_image = ImageTk.PhotoImage(image=pil_image)
        self.video_frame.configure(image=tk_image)
        self.video_frame.image = tk_image

    def use_frame(self):
        self.returned_image = self.current_frame
        self.close()

    def cancel(self):
        self.returned_image = None
        self.close()

    def close(self):
        self.cap.release()
        self.destroy()

    def get_image(self):
        self.wait_window()
        return self.returned_image


class Measurer(tkinter.Toplevel):
    def __init__(self, master, save_path, **kwargs):
        super().__init__(master=master, **kwargs)

        self.lift()

        self.MEASURED = False
        self.save_path = save_path
        self.pixel_values = {}
        self.lines = ["A", "B", "C", "D"]
        self.tooltips = {
            "A": "In TopView part, draw a line from the left inner edge\n to the right inner edge of the tank",
            "B": "In TopView part, draw a line from the top inner edge\n to the bottom inner edge of the tank",
            "C": "In FrontView part, draw a line, following the water surface,\n from the top inner edge to the bottom inner edge of the tank",
            "D": "In FrontView part, draw a line from the water surface\n to the right inner edge of the tank"
        }
        for key in self.tooltips.keys():
            self.tooltips[key] += "\nPress 'Enter' to confirm drawing\nPress 'Esc' to cancel drawing"

        self.ImageFrame = tkinter.Frame(self)
        self.Panel = tkinter.Frame(self, width=512)

        # set initial size of self.ImageFrame to 1024x768
        self.ImageFrame.config(width=1280, height=720)

        # Adjust Panel height
        if self.ImageFrame.winfo_reqheight() < 512:
            self.Panel.config(height=720)
        else:
            self.Panel.config(height=self.ImageFrame.winfo_reqheight())

        self.loadImageButton = tkinter.Button(self.ImageFrame, text="Load Image", command=self.load_image)
        self.loadImageButton.pack(expand=True)

        self.PanelTop = tkinter.Frame(self.Panel)
        self.PanelTop.pack(side=tkinter.TOP, expand=True, fill=tkinter.BOTH)

        self.PanelMiddle = tkinter.Frame(self.Panel)
        self.PanelMiddle.pack(side=tkinter.TOP, expand=True, fill=tkinter.BOTH)

        self.PanelBottom = tkinter.Frame(self.Panel)
        self.PanelBottom.pack(side=tkinter.BOTTOM, expand=True, fill=tkinter.BOTH)

        column_names = ['']
        self.names = {}
        for i in range(len(column_names)):
            self.names[0] = tkinter.Label(self.PanelTop, text=column_names[i])
            self.names[0].grid(row=0, column=i+1, padx=10, pady=10, sticky="nsew")

        self.draw_Buttons = {}
        self.pixel_values_Label = {}
        self.values_Entry = {}
        for i, line_name in enumerate(self.lines):
            self.draw_Buttons[line_name] = tkinter.Button(self.PanelTop, 
                                                          text="Draw Line " + line_name, 
                                                          command= lambda line_name=line_name: self.draw(line_name)
                                                          )
            self.draw_Buttons[line_name].grid(row=i+1, column=0, padx=10, pady=10, stick="nsew")

            self.pixel_values_Label[line_name] = tkinter.Label(self.PanelTop)
            self.pixel_values_Label[line_name].grid(row=i+1, column=1, padx=10, pady=10, stick="nsew")

            if line_name == "A":
                self.values_Entry[line_name] = tkinter.Entry(self.PanelTop)
                self.values_Entry[line_name].grid(row=i+1, column=2, padx=10, pady=10, stick="nsew")
                self.values_unit = tkinter.Label(self.PanelTop, text="cm")
                self.values_unit.grid(row=i+1, column=3, padx=10, pady=10, stick="nsew")


        self.Tip = tkinter.Label(self.PanelMiddle, text="Instructions: ")
        self.Tip.grid(row=0, column=0, padx=10, pady=10, stick="nsew")
        self.TipText = tkinter.Label(self.PanelMiddle)

        self.Button_Confirm = tkinter.Button(self.PanelBottom, text="Confirm", command=self.confirm_draw)
        self.Button_Confirm.grid(row=0, column=0, padx=10, pady=10, stick="nsew")
        self.Button_Cancel = tkinter.Button(self.PanelBottom, text="Cancel", command=self.cancel_draw)
        self.Button_Cancel.grid(row=0, column=1, padx=10, pady=10, stick="nsew")

        self.ImageFrame.pack(side=tkinter.LEFT, expand=True, fill=tkinter.BOTH)
        self.Panel.pack(side=tkinter.RIGHT, expand=True, fill=tkinter.BOTH)


    def load_image(self):
        file_path = tkinter.filedialog.askopenfilename()

        if not file_path:
            logger.debug("No file selected")
            return

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext in ['.mp4', '.avi', '.mov']:  # Add other video formats as needed
            # ref_frame_selector = RefFrameSelector(file_path, self)
            # image = ref_frame_selector.get_image()
            # [TODO] Add a function to get frame from chosen part of the video
            image = get_first_frame(file_path)
            if image is None:
                logger.debug("No frame selected")
                return
            # currently image is a numpy array, need to convert to PIL Image
            image = Image.fromarray(image)

        else:
            image = Image.open(file_path)
            logger.debug(f"Image loaded: {file_path}")
            logger.debug(f"Image size: {image.size}")

        # if file_path:
        #     image = Image.open(file_path)
        #     logger.debug(f"Image loaded: {file_path}")
        #     logger.debug(f"Image size: {image.size}")
        # else:
        #     logger.debug("No image selected")
        #     return
            
        # Resize the image
        # ratio = min(1024 / image.width, 768 / image.height)
        # image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.ANTIALIAS)
            
        self.tk_image = ImageTk.PhotoImage(image)

        # Lift and center the window
        self.lift()
        self.geometry("+%d+%d" % (self.winfo_screenwidth() / 2 - self.winfo_width() / 2, self.winfo_screenheight() / 2 - self.winfo_height() / 2))

        self.canvas = tkinter.Canvas(self.ImageFrame, width=self.tk_image.width(), height=self.tk_image.height())
        self.canvas.create_image(0, 0, anchor='nw', image=self.tk_image)
        self.canvas.pack()

        # bring the center of the window to the center of the screen
        logger.debug("winfo_screenwidth: {}, winfo_screenheight: {}".format(self.winfo_screenwidth(), self.winfo_screenheight()))
        self.geometry("+%d+%d" % (self.winfo_screenwidth() / 2 - self.winfo_width() / 2, self.winfo_screenheight() / 2 - self.winfo_height() / 2))


    def start_draw_session(self, line_name):

        # replace image in self.canvas with the original image
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor='nw', image=self.tk_image)

        self.canvas.bind("<Button-1>", self.button1_click)
        self.canvas.bind("<B1-Motion>", self.mouse_moving)
        self.canvas.bind("<ButtonRelease-1>", self.button1_release)
        # self.canvas.bind("<Button-3>", self.confirm_line)
        self.bind("<Return>", self.confirm_line)
        self.canvas.bind("<Button-3>", self.cancel_line)
        self.bind("<Escape>", self.cancel_line)
        # bind "Shift" to draw a straight line
        self.bind("<Shift_L>", self.draw_straight_line)
    
        self.line_name = line_name

        self.pseudo_window = tkinter.Toplevel(self)
        self.pseudo_window.withdraw()

        # wait for window to close before continuing
        self.pseudo_window.wait_window()

    def draw_straight_line(self, event):
        self.canvas.delete('line')
        temp_height = abs(event.y - self.start_point_temp[1])
        temp_width = abs(event.x - self.start_point_temp[0])
        if temp_width > temp_height:
            self.canvas.create_line(self.start_point_temp[0], self.start_point_temp[1], event.x, self.start_point_temp[1], fill="yellow", width=2, tags='line')
        elif temp_width < temp_height:
            self.canvas.create_line(self.start_point_temp[0], self.start_point_temp[1], self.start_point_temp[0], event.y, fill="yellow", width=2, tags='line')
        else:
            self.canvas.create_line(self.start_point_temp[0], self.start_point_temp[1], event.x, event.y, fill="yellow", width=2, tags='line')

    def button1_click(self, event):
        self.start_point_temp = event.x, event.y

    def mouse_moving(self, event):
        self.canvas.delete('line')
        self.canvas.create_line(self.start_point_temp[0], self.start_point_temp[1], event.x, event.y, fill="yellow", width=2, tags='line')

    def button1_release(self, event):
        self.end_point_temp = event.x, event.y
        logger.debug(f"start_point_temp: {self.start_point_temp}, end_point_temp: {self.end_point_temp}")
        self.canvas.unbind("<B1-Motion>")
        self.canvas.bind("<Button-1>", self.cancel_line)

    def confirm_line(self, event):
        self.pixel_values[self.line_name] = [self.start_point_temp, self.end_point_temp]
        logger.debug(f"Updated pixel_values: {self.pixel_values}")
        self.canvas.unbind("<Button-1>")
        self.canvas.unbind("<Button-2>")
        self.unbind("<Escape>")
        # self.canvas.unbind("<Button-3>")
        self.unbind("<Return>")
        self.canvas.unbind("<ButtonRelease-1>")
        self.canvas.unbind("<B1-Motion>")

        self.pseudo_window.destroy()

    def cancel_line(self, event):
        self.canvas.delete('line')
        self.canvas.unbind("<Button-1>")
        self.start_point_temp = event.x, event.y
        self.canvas.bind("<Button-1>", self.button1_click)
        self.canvas.bind("<B1-Motion>", self.mouse_moving)

    def draw(self, line_name):
        # tkinter.messagebox.showinfo("Instruction", self.tooltips[line_name])
        self.TipText.config(text=self.tooltips[line_name])
        try:
            self.TipText.grid(row=0, column=1, padx=10, pady=10, stick="nsew")
        except:
            pass
        # Wait for user to draw a line on the image and press Enter
        # Save the line length in self.pixel_values

        self.start_draw_session(line_name)

        logger.info(f"Starting point: {self.pixel_values[line_name][0]}")
        logger.info(f"Ending point: {self.pixel_values[line_name][1]}")

        distance = calculate_distance(self.pixel_values[line_name][0], self.pixel_values[line_name][1])
        logger.info("Distance: {}".format(distance))

        try:
            self.pixel_values_Label[line_name].config(text=str(distance))
        except:
            pass

    def get_real_values(self):

        real_values = {}

        for line_name in self.lines:
            if line_name in self.values_Entry:
                try:
                    real_values[line_name] = float(self.values_Entry[line_name].get())
                except:
                    tkinter.messagebox.showerror("Error", "Please enter a valid number for line {}".format(line_name))
                    return False
            else:
                try:
                    real_values[line_name] = float(self.values_Entry["A"].get())
                except:
                    tkinter.messagebox.showerror("Error", "Please enter a valid number for line A")
                    return False

        return real_values

    def confirm_draw(self):

        if self.save_path == None:        
            save_path = "Bin/essential_coords.json"
        else:
            save_path = self.save_path / "essential_coords.json"

        real_values = self.get_real_values()
        if real_values == False:
            return
        
        save_values = {}
        for line_name in self.pixel_values:
            save_values[line_name] = {
                "pixel": self.pixel_values[line_name],
                "real": real_values[line_name]
            }

        try:
            with open(save_path, 'w') as f:
                json.dump(save_values, f)
            logger.debug(f"Write essential coordinates successfully at Path = {save_path}")
        except:
            logger.debug(f"Write essential coordinates NOT successfully at Path = {save_path}")

        self.MEASURED = True
        self.destroy()


    def cancel_draw(self):
        self.MEASURED = False
        self.destroy()

############################################### DragDrop Boxes CLASS ################################################

class DragDropBox(customtkinter.CTkFrame):

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.bind("<Button-1>", self.start_drag)
        self.bind("<Button1-Motion>", self.drag)
        self.bind("<Button1-ButtonRelease>", self.drop)
        self.drag_data = {"x": 0, "y": 0, "id": None}

    def start_drag(self, event):
        self.drag_data["id"] = self.cget("text")
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def drag(self, event):
        self.place_configure(x=self.winfo_x() + event.x - self.drag_data["x"],
                             y=self.winfo_y() + event.y - self.drag_data["y"])

    def drop(self, event):
        self.drag_data["id"] = None
        self.drag_data["x"] = 0
        self.drag_data["y"] = 0

class BoxRearranger(tkinter.Toplevel):

    def __init__(self, master, **kw):
        super().__init__(master, **kw)

        self.title("Rearrange Boxes")

        self.BOX_NUM = 6 # [TODO] This should be changed to be dynamic, based on the input dfs

        self.FixedBoxes_Frame = customtkinter.CTkFrame(self)
        self.FixedBoxes_Frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.fixed_boxes = []

        for i in range(self.BOX_NUM):
            self.fixed_boxes.append(customtkinter.CTkFrame(self.FixedBoxes_Frame, text="Box {}".format(i+1)))
            self.fixed_boxes[i].grid(row=i, column=0, padx=10, pady=10, sticky="nsew")

        self.DragDropBoxes_Frame = customtkinter.CTkFrame(self)
        self.DragDropBoxes_Frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.drag_drop_boxes = []

        for i in range(self.BOX_NUM):
            self.drag_drop_boxes.append(DragDropBox(self.DragDropBoxes_Frame, text="Box {}".format(i+1)))
            self.drag_drop_boxes[i].grid(row=i, column=0, padx=10, pady=10, sticky="nsew")


class ToolTip(object):

    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0

    def showtip(self, text):
        "Display text in tooltip window"
        self.text = text
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 57
        y = y + cy + self.widget.winfo_rooty() +27
        self.tipwindow = tw = tkinter.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry("+%d+%d" % (x, y))
        label = tkinter.Label(tw, text=self.text, justify=tkinter.LEFT,
                      background="#ffffe0", relief=tkinter.SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

def CreateToolTip(widget, text):
    toolTip = ToolTip(widget)
    def enter(event):
        toolTip.showtip(text)
    def leave(event):
        toolTip.hidetip()
    widget.bind('<Enter>', enter)
    widget.bind('<Leave>', leave)

############################################### CUSTOM BIG WIDGETS CLASS ################################################
class ScrollableProjectList(customtkinter.CTkScrollableFrame):

    def __init__(self, master, command=None, **kwargs):

        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.command = command
        self.project_variable = customtkinter.StringVar()
        self.project_radiobuttons = []

    def add_project(self, project_name):
        project_radiobutton = customtkinter.CTkRadioButton(
            self, text=project_name, value=project_name, variable=self.project_variable
        )
        project_radiobutton.grid(row=len(self.project_radiobuttons), column=0, pady=(0, 10), sticky="w")
        self.project_radiobuttons.append(project_radiobutton)

    def clear_projects(self):
        for radiobutton in self.project_radiobuttons:
            radiobutton.destroy()
        self.project_radiobuttons = []

    def get_selected_project(self):
        return self.project_variable.get()

    def set_selected_project(self, project_name="last"):
        if project_name == "last":
            # set to the last project in list
            self.project_variable.set(self.project_radiobuttons[-1].cget("text"))
            logger.warning("Set project variable failed, set to the last project in list")
        else:
            self.project_variable.set(project_name)
            logger.debug("Set project variable to " + project_name)
    
    def select_project(self, project_name):
        for radiobutton in self.project_radiobuttons:
            if radiobutton.cget("text") == project_name:
                radiobutton.invoke()
                break

    def return_recent_project(self):
        return self.project_radiobuttons[-1].cget("text")
    

class ProjectDetailFrame(customtkinter.CTkScrollableFrame):

    def __init__(self, master, project_name, **kwargs):

        super().__init__(master, **kwargs)

        # # Create tree view
        # self.tree = ttkinter.Treeview(self, height = 5, show = "headings")
        # self.tree.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        

        # If project name is not empty, load the project details, 
        # otherwise, display "No project selected"
        self.project_name = project_name
        if self.project_name != "":
            self.load_project_details()
        else:
            label = customtkinter.CTkLabel(self, text="No project selected")
            label.grid(row=0, column=0, padx=5, pady=5)

    def update_grid_weight(self):
        rows, cols = self.grid_size()

        for row in range(rows):
            self.grid_rowconfigure(row, weight=1)

        for col in range(cols):
            self.grid_columnconfigure(col, weight=1)

    def load_project_details(self, project_name=None, batch_name="Batch 1"):

        logger.info(f"Loading.. project name = {project_name}")

        if project_name == "":
            label = customtkinter.CTkLabel(self, text="No project selected")
            label.grid(row=0, column=0, padx=5, pady=5)
            return

        if project_name is not None:
            self.project_name = project_name

        with open(HISTORY_PATH, "r") as file:
            projects_data = json.load(file)

        project_data = projects_data[self.project_name][batch_name]

        logger.info(project_data)

        headers = ["Treatment", 
                   "Dose", 
                   "Dose Unit", 
                #    "Fish Number", 
                   "Note"
                   ]

        for i, header in enumerate(headers):
            label = customtkinter.CTkLabel(self, text=header, font=customtkinter.CTkFont(weight="bold"))
            label.grid(row=0, column=i, padx=5, pady=5)

        for row, (treatment, details) in enumerate(project_data.items(), start=1):
            # treatment_name, dose, dose_unit, fish_number, note = details
            treatment_name, dose, dose_unit, note = details

            dose = dose if dose != 0 else ""
            dose_unit = dose_unit if dose_unit != "" else ""
            # fish_number = fish_number if fish_number != 0 else ""

            labels = [treatment_name, 
                      dose, 
                      dose_unit, 
                    #   fish_number, 
                      note]

            for col, label_text in enumerate(labels):
                label = customtkinter.CTkLabel(self, text=label_text)
                label.grid(row=row, column=col, padx=5, pady=5)

        self.update_grid_weight()

    def clear(self):
        for child in self.winfo_children():
            child.destroy()


class HISTORY():

    def __init__(self, history_path = HISTORY_PATH):
        self.history_path = history_path

        with open(HISTORY_PATH, "r") as file:
            self.projects_data = json.load(file)


    def reload(self):
        with open(HISTORY_PATH, "r") as file:
            self.projects_data = json.load(file)


    def find_dir(self, project_name):
        tkinter.messagebox.showerror("Error", "Project directory does not exist!")
        logger.info(f"Project directory of {project_name} does not exist. Asking for relocation")
        relocate = tkinter.messagebox.askyesno("Project not found", "Do you want to relocate it?")
        if relocate:
            # ask for new input of project_dir
            new_dir = tkinter.filedialog.askdirectory()
            
            self.projects_data[project_name]["DIRECTORY"] = new_dir
            self.saver()
            logger.info(f"Project directory of {project_name} has been relocated to {new_dir}")

            return new_dir
        else:
            return None

    def get_project_dir(self, project_name):
        self.reload()

        if project_name == "":
            logger.warning("Tried to get project directory of an empty project name")
            return None
        try:
            project_dir = self.projects_data[project_name]["DIRECTORY"]
        except KeyError:
            project_dir = self.find_dir(project_name)


        # check if the project directory exists
        if not os.path.exists(project_dir):
            project_dir = self.find_dir(project_name)

        return project_dir       
     

    def add_treatment(self, project_name, batch_name, treatment_char, substance, dose, dose_unit, note=""):

        if project_name == "":
            logger.warning("Tried to add treatment to an empty project name")
            return

        if substance == "":
            logger.warning("Tried to add treatment with empty treatment name")
            return

        if batch_name == "":
            logger.warning("Tried to add treatment with empty batch name")
            return

        if project_name not in self.projects_data:
            logger.warning(f"Project name {project_name} not found in history file")
            return

        if batch_name not in self.projects_data[project_name]:
            logger.warning(f"Batch name {batch_name} not found in history file")
            return

        if f"Treatment {treatment_char}" in self.projects_data[project_name][batch_name]:
            logger.warning(f"Treatment {treatment_char} already exists in history file")
            choice = tkinter.messagebox.askyesno("Treatment already exists", "Do you want to overwrite it?")
            if choice:
                pass
            else:
                return
            
        self.projects_data[project_name][batch_name][f"Treatment {treatment_char}"] = [substance, dose, dose_unit, note]

        self.saver()


    def saver(self):
        with open(self.history_path, "w") as file:
            json.dump(self.projects_data, file, indent=4)


class InputWindow(tkinter.Toplevel):

    def __init__(self, master, project_name, project_created=False, **kwargs):
        super().__init__(master, **kwargs)

        logger.info("Project input window opened")


        # set window size
        self.geometry("460x500")

        self.title("Project Input")

        self.CURRENT_PROJECT = project_name
        self.PROJECT_CREATED = project_created
        self.batch_name = "Batch 1"
        self.BOLD_FONT = customtkinter.CTkFont(size = 15, weight="bold")

        self.TOTAL_INFO = {}

        self.treatment_widgets = []

        self.rowconfigure(0, weight=1)
        # Top Canvas
        self.top_canvas = customtkinter.CTkScrollableFrame(self, width = 440)
        # expand the canvas to fill the window
        self.top_canvas.grid(row=0, column=0, sticky="nsew")

        self.ROW=0
        # Project name
        project_name_label = customtkinter.CTkLabel(self.top_canvas, text="Project name:", font=self.BOLD_FONT)
        project_name_label.grid(row=self.ROW, column=0, pady=5)
        self.project_name_entry = customtkinter.CTkEntry(self.top_canvas)
        self.project_name_entry.grid(row=self.ROW, column=1, pady=5)

        self.DoseToggler = customtkinter.CTkCheckBox(self.top_canvas, text="Have Dose", command=self.toggle_dose)
        self.DoseToggler.grid(row=self.ROW, column=2, pady=5)
        self.DoseToggler.select()


        self.ROW+=1
        # Common substance
        common_substance_label = customtkinter.CTkLabel(self.top_canvas, text="Common substance:", font=self.BOLD_FONT)
        common_substance_label.grid(row=self.ROW, column=0, pady=5)
        self.common_substance_entry = customtkinter.CTkEntry(self.top_canvas)
        self.common_substance_entry.grid(row=self.ROW, column=1, pady=5)

        hover_button = tkinter.Button(self.top_canvas, text="?")
        hover_button.grid(row=self.ROW, column=2, pady=5)
        CreateToolTip(hover_button, text = 'Common condition in all group\n'
                    'Can be left blank\n'
                    'The info you put here would be saved as Note\n'
                    'Group A is default as Control, you can change at your own will'
        )


        self.ROW+=1
        # Treatment A (Control)
        treatment_a_label = customtkinter.CTkLabel(self.top_canvas, text="Group A:", font=self.BOLD_FONT)
        treatment_a_label.grid(row=self.ROW, column=0, pady=5)
        self.treatment_a_entry = customtkinter.CTkEntry(self.top_canvas)
        self.treatment_a_entry.grid(row=self.ROW, column=1, pady=5)
        self.treatment_a_entry.insert(0, "Control")

        self.ROW+=1
        # Dose
        dose_label = customtkinter.CTkLabel(self.top_canvas, text="Dose:")
        dose_label.grid(row=self.ROW, column=0, pady=5)
        self.dose_a_entry = customtkinter.CTkEntry(self.top_canvas)
        self.dose_a_entry.grid(row=self.ROW, column=1, pady=5)
        self.unit_a_optionmenu = customtkinter.CTkOptionMenu(self.top_canvas, values=["ppm", "ppb"])
        self.unit_a_optionmenu.grid(row=self.ROW, column=2, pady=5)


        # self.ROW+=1
        # Fish number
        # fish_number_a_label = customtkinter.CTkLabel(self.top_canvas, text="Fish Number:")
        # fish_number_a_label.grid(row=self.ROW, column=0, pady=5)
        # self.fish_number_a_entry = customtkinter.CTkEntry(self.top_canvas)
        # self.fish_number_a_entry.grid(row=self.ROW, column=1, pady=5)
        
        self.ROW+=1
        # Treatment B
        treatment_b_label = customtkinter.CTkLabel(self.top_canvas, text="Group B:", font=self.BOLD_FONT)
        treatment_b_label.grid(row=self.ROW, column=0, pady=(20, 5))
        self.treatment_b_entry = customtkinter.CTkEntry(self.top_canvas)
        self.treatment_b_entry.grid(row=self.ROW, column=1, pady=(20, 5))

        self.ROW+=1
        # Dose
        dose_label = customtkinter.CTkLabel(self.top_canvas, text="Dose:")
        dose_label.grid(row=self.ROW, column=0, pady=5)
        self.dose_b_entry = customtkinter.CTkEntry(self.top_canvas)
        self.dose_b_entry.grid(row=self.ROW, column=1, pady=5)
        self.unit_b_optionmenu = customtkinter.CTkOptionMenu(self.top_canvas, values=["ppm", "ppb"])
        self.unit_b_optionmenu.grid(row=self.ROW, column=2, pady=5)

        # self.ROW+=1
        # Fish number
        # fish_number_b_label = customtkinter.CTkLabel(self.top_canvas, text="Fish Number:")
        # fish_number_b_label.grid(row=self.ROW, column=0, pady=5)
        # self.fish_number_b_entry = customtkinter.CTkEntry(self.top_canvas)
        # self.fish_number_b_entry.grid(row=self.ROW, column=1, pady=5)

        # Bottom Canvas
        bottom_canvas = customtkinter.CTkFrame(self)
        bottom_canvas.grid(row=1, column=0, sticky="nsew")

        # Add button
        add_button = customtkinter.CTkButton(bottom_canvas, text="Add Treatment", 
                                                command=self.add_treatment)
        add_button.grid(row=0, column=0, padx=5, pady=20)

        # Confirm button
        confirm_button = customtkinter.CTkButton(bottom_canvas, text="CONFIRM", 
                                                    font = self.BOLD_FONT,
                                                    command=self.get_values)
        confirm_button.grid(row=1, column=0, padx=5, pady=20)

        # Cancel button
        cancel_button = customtkinter.CTkButton(bottom_canvas, text="CANCEL", 
                                                font = self.BOLD_FONT,
                                                command=self.cancel_button_command)
        cancel_button.grid(row=1, column=1, padx=5, pady=20)

        self.wait_window()


    def toggle_dose(self):

        if self.DoseToggler.get() == 1:
            self.dose_a_entry.configure(state="normal")
            self.unit_a_optionmenu.configure(state="normal")
            self.dose_b_entry.configure(state="normal")
            self.unit_b_optionmenu.configure(state="normal")
            for widget in self.treatment_widgets:
                widget[1].configure(state="normal")
                widget[2].configure(state="normal")
        else:
            self.dose_a_entry.configure(state="disabled")
            self.unit_a_optionmenu.configure(state="disabled")
            self.dose_b_entry.configure(state="disabled")
            self.unit_b_optionmenu.configure(state="disabled")
            for widget in self.treatment_widgets:
                widget[1].configure(state="disabled")
                widget[2].configure(state="disabled")

    
    def get_dose_value(self, dose_entry, unit_entry):
        try:
            dose = float(dose_entry.get())
            unit = unit_entry.get()
        except ValueError:
            dose = ""      
            unit = ""  
        return dose, unit


    def add_treatment(self):
        logger.debug("Add treatment button clicked")

        treatment_row = len(self.treatment_widgets)*3 + self.ROW + 1
        treatment_name = f"Treatment {chr(ord('C') + len(self.treatment_widgets))}:"

        treatment_label = customtkinter.CTkLabel(self.top_canvas, text=treatment_name, font=self.BOLD_FONT)
        treatment_label.grid(row=treatment_row, column=0, pady=(20, 5))
        treatment_entry = customtkinter.CTkEntry(self.top_canvas)
        treatment_entry.grid(row=treatment_row, column=1, pady=(20, 5))

        dose_label = customtkinter.CTkLabel(self.top_canvas, text="Dose:")
        dose_label.grid(row=treatment_row + 1, column=0, pady=5)
        dose_entry = customtkinter.CTkEntry(self.top_canvas)
        dose_entry.grid(row=treatment_row + 1, column=1, pady=5)
        unit_optionmenu = customtkinter.CTkOptionMenu(self.top_canvas, values=["ppm", "ppb"])
        unit_optionmenu.grid(row=treatment_row + 1, column=2, pady=5)

        # fish_number_label = customtkinter.CTkLabel(self.top_canvas, text="Fish Number:")
        # fish_number_label.grid(row=treatment_row + 2, column=0, pady=5)
        # fish_number_entry = customtkinter.CTkEntry(self.top_canvas)
        # fish_number_entry.grid(row=treatment_row + 2, column=1, pady=5)

        self.treatment_widgets.append((treatment_entry, 
                                       dose_entry, 
                                       unit_optionmenu, 
                                    #    fish_number_entry
                                       ))


    def get_values(self):
        project_name = self.project_name_entry.get()
        self.CURRENT_PROJECT = project_name
        try:
            note = self.common_substance_entry.get()
        except:
            note = ""
        a_dose, a_unit = self.get_dose_value(self.dose_a_entry, self.unit_a_optionmenu)
        b_dose, b_unit = self.get_dose_value(self.dose_b_entry, self.unit_b_optionmenu)
        try:
            treatment_list = {
                "Treatment A": [
                    self.treatment_a_entry.get(),
                    a_dose,
                    b_dose,
                    # int(self.fish_number_a_entry.get()),
                    note
                ],
                "Treatment B": [
                    self.treatment_b_entry.get(),
                    b_dose,
                    b_unit,
                    # int(self.fish_number_b_entry.get()),
                    note
                ]
            }
        except Exception as e:
            #show message box of error
            print(e)
            tkinter.messagebox.showerror("Error", "Please fill the required fields with right type of value")

        for i, (treatment_entry, 
                dose_entry, 
                unit_optionmenu, 
                # fish_number_entry
                ) in enumerate(self.treatment_widgets):
            treatment_name = f"Treatment {chr(ord('C') + i)}"
            dose, unit = self.get_dose_value(dose_entry, unit_optionmenu)
            treatment_list[treatment_name] = [
                treatment_entry.get(),
                dose,
                unit,
                # int(fish_number_entry.get()),
                note
            ]

        # Save values to projects.json
        project_data = {
            project_name: {
                self.batch_name : treatment_list
                }
            }

        try:
            with open(HISTORY_PATH, "r") as file:
                existing_data = json.load(file)
            if project_name in existing_data:
                # Display message box of error
                tkinter.messagebox.showerror("Error", "Project already exists")
            else:
                existing_data.update(project_data)
                self.PROJECT_CREATED = True
                with open(HISTORY_PATH, "w") as file:
                    json.dump(existing_data, file, indent=2)
                self.destroy()  # Move this line inside the else block
        except:
            existing_data = project_data
            self.PROJECT_CREATED = True
            with open(HISTORY_PATH, "w") as file:
                json.dump(existing_data, file, indent=2)
            self.destroy()  # Move this line inside the except block


    def cancel_button_command(self):
        logger.debug("Cancel button clicked")

        self.PROJECT_CREATED = False
        self.destroy()

    def status(self):

        return self.CURRENT_PROJECT, self.PROJECT_CREATED
    

class WidgetParameters(customtkinter.CTkScrollableFrame):

    def __init__(self, master, project_dir=None, *args, **kwargs):
        
        super().__init__(master, *args, **kwargs)

        if project_dir == None or project_dir == "":
            self.project_dir = TEMPLATE_PATH
        else:
            self.project_dir = project_dir
            
        self.project_name = Path(self.project_dir).name

        self.null_label = None
        self.hyp_name = "parameters.json"
        self.ec_name = "essential_coords.json"
        self.UNITS = {
            "DURATION": "seconds",
            "FRAME RATE": "frames/second",
            # "AV INTERVAL": "frames",
            "X POSITION": "",
            "CENTER X": "",
            "CONVERSION SV": "pixels/cm",
            "Y POSITION": "",
            "CENTER Y": "",
            "CONVERSION TV": "pixels/cm",
            "UPPER": "",
            "LOWER": "",
            "CENTER Z": "",
            "Z POSITION": "",
            "CORR TYPE": ""
        }

        self.null_label_check()

        self.DATA_ZERO = {k: 0 for k in list(self.UNITS.keys())}
        self.DATA_ZERO['CORR TYPE'] = "pearson"

        if self.project_name == "":
            self.null_label = customtkinter.CTkLabel(self, text="No project selected")
            self.null_label.grid(row=0, column=0, padx=5, pady=5)
        else:
            self.load_parameters()

        self.entries = {}


    def null_label_check(self):
        logger.debug(f"{self.null_label=}")
        if self.null_label == None:
            # Destroy null_label_notif if it exists
            logger.debug("Destroying null_label_notif")
            try:
                self.null_label_notif.destroy()
            except:
                pass
            return
        
        self.null_label_notif = customtkinter.CTkLabel(self, text="No parameters found, \nPress Load Project again to open Measurer window")
        self.null_label_notif.grid(row=0, column=0, padx=5, pady=5)

        
    def OpenMeasurerWindow(self, project_dir, batch_num, treatment_char):
        save_path = get_static_dir(project_dir=project_dir, 
                                batch_num=batch_num,
                                treatment_char=treatment_char
                                )

        MeasurerWindow = Measurer(self.master, save_path=save_path)

        def on_close():
            MeasurerWindow.destroy()
            self.master.focus_set()

        MeasurerWindow.protocol("WM_DELETE_WINDOW", on_close)
        MeasurerWindow.wait_window()

        return MeasurerWindow.MEASURED


    # def OpenMeasurerWindow(self, project_dir, batch_num, treatment_char):

    #     save_path = get_static_dir(project_dir=project_dir, 
    #                                batch_num=batch_num,
    #                                treatment_char=treatment_char
    #                                )

    #     MeasurerWindow = Measurer(self.master, save_path=save_path)
    #     MeasurerWindow.mainloop()

    #     return MeasurerWindow.MEASURED

    def get_hyp_path(self, project_dir, batch_num, treatment_char):

        static_dir = get_static_dir(project_dir=project_dir,
                                    batch_num=batch_num,
                                    treatment_char=treatment_char)
        
        hyp_path = static_dir / self.hyp_name
        ec_path = static_dir / self.ec_name

        logger.debug(f"Retrieved hyp from {hyp_path}")

        return hyp_path, ec_path
        
    
    def get_current_entry_quantity(self):

        last_row = list(self.entries.keys())[-1]
        last_entry = self.entries[last_row]

        try:
            last_row_num = int(last_row.split('_')[-1])
            return last_row_num
        except:
            return 0
        
    def MeasureAndCalculate(self, project_dir=None, batch_num=1, treatment_char="A"):
        logger.info("Opening Measurer Window")
        MEASURED = self.OpenMeasurerWindow(project_dir = project_dir,
                                        batch_num = batch_num,
                                        treatment_char = treatment_char)

        if MEASURED:
            logger.info("Measurer window closed after measuring")
        else:
            logger.warning("Measurer window closed without measuring")
            return

        logger.info("Calculating parameters")
        try:
            _ = ParamsCalculator(project_dir = project_dir,
                                batch_num = batch_num,
                                treatment_char = treatment_char)
            logger.info("Parameters (re-)calculated")
        except:
            logger.warning("Error in calculating parameters, please check the Measuring process")

        logger.info("Measured completed, loading parameters")
        self.load_parameters(project_dir, batch_num, treatment_char)
        self.null_label_check()
        

    def load_parameters(self, project_dir=None, batch_num=1, treatment_char="A"):

        if project_dir == None:
            project_dir = self.project_dir
            project_name = self.project_name
        else:
            project_name = Path(project_dir).name

        logger.debug(f"Loading parameters for project_name = {project_name}, batch_num = {batch_num}, treatment = {treatment_char}")

        self.null_label = None

        self.entries = {}

        self.clear()

        if project_dir == "":
            self.hyp_path = TEMPLATE_PATH / 'static' / self.hyp_name
        else:
            self.hyp_path, self.ec_path = self.get_hyp_path(project_dir, batch_num, treatment_char)

        try:
            logger.debug("Trying to load parameters from json file")
            with open(self.hyp_path, "r") as file:
                ori_dict = json.load(file)

        except:
            logger.debug("Unable to load parameters from json file")
            logger.debug("Trying to measure parameters using given essential_coords")
            try:
                _ = ParamsCalculator(project_dir = project_dir,
                                    batch_num = batch_num,
                                    treatment_char = treatment_char)
                logger.info("Parameters (re-)calculated")
                with open(self.hyp_path, "r") as file:
                    ori_dict = json.load(file)
            except:
                logger.info("Unable to calculate parameters, asking user to re-measure")

                message = "No parameters found, Do you want to open Measurer Window to generate parameters?"
                choice = tkinter.messagebox.askyesno("No parameters found", message)
                if choice == True:
                    self.MeasureAndCalculate(project_dir=project_dir, 
                                             batch_num=batch_num, 
                                             treatment_char=treatment_char)
                    # logger.info("Opening Measurer Window")
                    # MEASURED = self.OpenMeasurerWindow(project_dir = project_dir,
                    #                                 batch_num = batch_num,
                    #                                 treatment_char = treatment_char)

                    # if MEASURED:
                    #     logger.info("Measurer window closed after measuring")
                    # else:
                    #     logger.warning("Measurer window closed without measuring")
                    #     return

                    # logger.info("Calculating parameters")
                    # try:
                    #     _ = ParamsCalculator(project_dir = project_dir,
                    #                         batch_num = batch_num,
                    #                         treatment_char = treatment_char)
                    #     logger.info("Parameters (re-)calculated")
                    # except:
                    #     logger.warning("Error in calculating parameters, please check the Measuring process")

                    # logger.info("Measured completed, loading parameters")
                    # self.load_parameters(project_dir, batch_num, treatment_char)
                    # self.null_label_check()
                else:
                    logger.info("User chose not to open Measurer Window")
                    self.null_label_check()
                    return

        
        display_dict = {k: v for k, v in ori_dict.items() if not isinstance(v, (dict, list))}

        if 'CORR TYPE' not in display_dict:
            display_dict['CORR TYPE'] = "pearson"

        headers = ["Parameter", "Value", "Unit"]
        
        example_key = list(display_dict.keys())[0]
        units = [self.UNITS[k] for k in display_dict.keys()]
        for i, unit in enumerate(units):
            unit_label = customtkinter.CTkLabel(self, text=unit)
            unit_label.grid(row=i+1, column=2, padx=(5,10), pady=5)

        self.key_labels = {}

        for row, (key, value) in enumerate(display_dict.items()):
            self.key_labels[key] = customtkinter.CTkLabel(self, text=key)
            self.key_labels[key].grid(row=row+1, column=0, padx=5, pady=5)

            value_entry = customtkinter.CTkEntry(self)
            value_entry.insert(0, value)
            value_entry.grid(row=row+1, column=1, padx=5, pady=5)

            entry_key = key

            self.entries[entry_key] = value_entry

        # make a header
            for i, header in enumerate(headers):
                label = customtkinter.CTkLabel(self, text=header, font=customtkinter.CTkFont(weight="bold"))
                label.grid(row=0, column=i, padx=5, pady=5)


    def clear(self):
        for child in self.winfo_children():
            child.destroy()

    def save_parameters(self, project_dir, batch_num, treatment_char, save_target):
        logger.debug(f"Saving parameters for {Path(project_dir).name}.Batch {batch_num}.Treatment {treatment_char}, save_target = {save_target}")

        def get_entry(entry_dict):
            out_dict = {}
            for key, value in entry_dict.items():
                try:
                    if isinstance(value, list):
                        v = [float(value[0].get()), float(value[1].get())]
                    # check if the value is a string or a float
                    elif str(value).isdigit():
                        v = float(value.get())
                    else:
                        v = value.get()
                except AttributeError:
                    logger.warning(f"During saving parameters for {Path(project_dir).name}.Batch {batch_num}.Treatment {treatment_char}")
                    logger.warning(f"AttributeError: {key} is not a tkinter entry")
                    logger.warning(f"Value: ", v)
                    logger.warning(f"Value type: ", type(v))
                    continue
                out_dict[key] = v
            return out_dict
        
        if project_dir == "":
            tkinter.messagebox.showerror("Warning", "No project selected. No save was made.")
            return 
        else:
            self.hyp_path, self.ec_path = self.get_hyp_path(project_dir, batch_num, treatment_char)

        # Get the values from the entries
        updated_values = get_entry(self.entries)
        
        # load the original data
        try:
            with open(self.hyp_path, "r") as file:
                parameters_data = json.load(file)
        except:
            parameters_data = self.DATA_ZERO

        # Update the values in the dictionary with the new values
        for key, value in updated_values.items():
            try:
                parameters_data[key] = value
            except ValueError:
                logger.warning(f"Invalid input for {key}: {value}. Skipping.")
        

        # Save the updated data to the file
        with open(self.hyp_path, "w") as file:
            json.dump(parameters_data, file, indent=4)

        logger.info(f"Parameters saved to {self.hyp_path}.")
        
        if save_target != "self":
            for target_char in save_target:
                target_hyp_path, target_ec_path = self.get_hyp_path(project_dir, batch_num, target_char)
                # Dump data to target_hyp_path
                with open(target_hyp_path, "w") as file:
                    json.dump(parameters_data, file, indent=4)
                    logger.debug(f"Parameters from {treatment_char} saved to {target_char}.")
                
                # Copy essential_coords.json from self.ec_path to target_ec_path
                shutil.copy(self.ec_path, target_ec_path)
                logger.debug(f"Essential coords from {treatment_char} saved to {target_char}.")



class TickBoxWindow(tkinter.Toplevel):

    def __init__(self, master, values, box_command=None, **kwargs):
        super().__init__(master, **kwargs)

        self.values = values
        self.master = master

        # Configure window size
        self.geometry("250x250")

        self.tickboxes = {}

        ROW = 0

        tickbox_height = 30
        tickbox_padx = 30
        tickbox_pady = 10
        element_height = tickbox_height + tickbox_pady
        max_tickbox_width = 0

        font = ("Arial", 14)

        # Configure custom style for the ttk.Checkbutton
        custom_style = ttk.Style()
        custom_style.configure("Custom.TCheckbutton", font=font)

        for i, value in enumerate(self.values):
            tickbox = ttk.Checkbutton(self, text=value, style="Custom.TCheckbutton")

            if box_command:
                tickbox.configure(command=box_command)

            tickbox.grid(row=ROW, column=0, padx=tickbox_padx, pady=tickbox_pady, sticky="w")

            # Measure the width of the checkbox widget, not the text itself
            tickbox_width = tickbox.winfo_reqwidth()

            if tickbox_width > max_tickbox_width:
                max_tickbox_width = tickbox_width

            self.tickboxes[value] = tickbox

            # set default unchecked
            tickbox.state(['!alternate'])

            ROW += 1

        self.ButtonFrame = tkinter.Frame(self)
        self.ButtonFrame.grid(row=ROW, column=0, padx=tickbox_padx, pady=tickbox_pady)
        ROW += 1

        window_width = max_tickbox_width + tickbox_padx * 2
        window_height = element_height * len(self.values) + 100

        self.ConfirmButton = tkinter.Button(self.ButtonFrame, text="Confirm", command=self.confirm)
        self.ConfirmButton.pack(side="left", fill="both", expand=True, padx=10)

        # Configure window height to fit all tickboxes
        self.update_idletasks()
        self.geometry(f"{window_width}x{window_height}")

        # self.wait_window()

    def ticked_boxes(self):
        ticked = [key for key, value in self.tickboxes.items() if value.instate(['selected'])]
        logger.debug(f"{ticked=}")
        return ticked
    

    def confirm(self):
        self.TickedTreatmentBoxes = self.ticked_boxes()
        logger.debug(f"{self.TickedTreatmentBoxes=}")
        logger.debug("Updated TickedTreatmentBoxes")
        self.destroy()