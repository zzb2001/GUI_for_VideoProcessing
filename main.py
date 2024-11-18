import numpy as np
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import QTimer, QThread, Signal
import cv2
import subprocess
import time
import os
import random
import yaml
import json
from PIL import Image, ImageDraw

with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

if not os.path.exists(config['hand_result_path']):
    os.makedirs(config['hand_result_path'])
if not os.path.exists(config['hand_result_img_path']):
    os.makedirs(config['hand_result_img_path'])
if not os.path.exists(config['final_video_path']):
    os.makedirs(config['final_video_path'])

uiLoader = QUiLoader()


class LoadThread(QThread):
    progress = Signal(bool)

    def __init__(self, parameters):
        super(LoadThread, self).__init__()
        self.parameters = parameters

    def run(self):
        # TODO:替换下列代码
        time.sleep(random.uniform(1, 2))

        self.progress.emit(True)


class HandThread(QThread):
    success = Signal(bool)

    def __init__(self, input_path, output_path, img_path, file_path):
        super(HandThread, self).__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.img_path = img_path
        self.file_path = file_path

    def run(self):
        try:
            # subprocess.run(['AnyLabeling', '1.png', '--output', 'result', '--autosave'])
            subprocess.run(['AnyLabeling', self.input_path, '--output', self.file_path])

            image = Image.open(self.input_path)
            draw = ImageDraw.Draw(image)

            with open(self.output_path, 'r') as f:
                data = json.load(f)

            for shape in data.get('shapes', []):
                points = shape.get('points', [])
                if len(points) > 1:
                    points = [(int(p[0]), int(p[1])) for p in points]
                    draw.polygon(points, outline="red", fill=None)

            image.save(self.img_path)
            self.success.emit(True)

            # arguments = ['1.png','--output': '1.json']
            # subprocess.run(['labelme.exe']+arguments)
            # subprocess.Popen(['labelme ' + self.input_path + ' --output' + self.output_path])
        except Exception as e:
            print(f"Error : {e}")


class IntegrationThread(QThread):
    success = Signal(bool)

    def __init__(self, enhanced_img_path, hand_marked_img_path, output_path, FPS=config['FPS']):
        super(IntegrationThread, self).__init__()
        self.enhanced_img_path = enhanced_img_path
        self.output_path = output_path
        self.hand_marked_img_path = hand_marked_img_path
        self.FPS = FPS

    def run(self):
        try:
            e_imgs = os.listdir(self.enhanced_img_path)
            m_imgs = os.listdir(self.hand_marked_img_path)

            sample_image = cv2.imread(os.path.join(self.enhanced_img_path, e_imgs[0]))
            height, width, layers = sample_image.shape
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video = cv2.VideoWriter(self.output_path, fourcc, self.FPS, (width, height))

            for img_name in e_imgs:
                if img_name in m_imgs:
                    img_path = os.path.join(self.hand_marked_img_path, img_name)
                else:
                    img_path = os.path.join(self.enhanced_img_path, img_name)
                frame = cv2.imread(img_path)
                video.write(frame)

            self.success.emit(True)

        except Exception as e:
            print(f"Error : {e}")


class MainWindow:

    def __init__(self):
        self.filename = None
        self.filename_without_extension = None
        self.origin_img = None
        self.is_fixed = False

        self.ui = uiLoader.load('UI/main_window.ui')
        self.ui.open.triggered.connect(self.open_file)
        self.ui.save.triggered.connect(self.save_file)
        self.ui.set_FPS.triggered.connect(self.open_FPS_dialog)
        self.ui.display_FPS.triggered.connect(self.display_FPS)
        self.ui.current_index.valueChanged.connect(self.change_result)

        self.ui.btn_begin_or_pause.clicked.connect(self.control_video)
        self.ui.btn_begin_or_pause_3.clicked.connect(self.control_video_f)
        self.ui.video_progress.sliderPressed.connect(self.slider_pressed)
        self.ui.video_progress.sliderReleased.connect(self.jump_by_ratio)
        self.ui.video_progress_3.sliderPressed.connect(self.slider_pressed_3)
        self.ui.video_progress_3.sliderReleased.connect(self.jump_by_ratio_3)
        self.ui.btn_replay.clicked.connect(self.video_replay)
        self.ui.btn_replay_3.clicked.connect(self.video_replay_f)
        self.ui.btn_upload.clicked.connect(self.open_file)
        self.ui.btn_sort.clicked.connect(self.get_sotred_result)
        self.ui.btn_prev.clicked.connect(self.prev_result)
        self.ui.btn_next.clicked.connect(self.next_result)
        self.ui.btn_mark.clicked.connect(self.hand_mark)
        self.ui.btn_integrate.clicked.connect(self.integrate_video)

        # 初始化相关
        self.ui.loading_widget.hide()
        self.ui.setGeometry(200, 200, 600, 400)
        self.ui.btn_begin_or_pause.setText('播放')
        self.ui.tabWidget.hide()
        self.load_thread = None
        self.current_frame = 0
        self.ui.FPS_label.hide()
        self.ui.FPS_label_3.hide()
        self.sorted_results = None
        self.current_page = 0

        # 定时器设置
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(round(1000 / config['FPS']))  # 每40ms更新一次帧 FPS:25

        self.timer_f = QTimer()
        self.timer_f.timeout.connect(self.update_frame_f)
        self.timer_f.start(round(1000 / config['FPS']))  # 每40ms更新一次帧 FPS:25

        self.ui.FPS_label.setText('FPS : ' + str(round(1000 / 40)) + '    ')

        self.is_load = False
        self.dots = 0
        self.loading_timer = QTimer()
        self.loading_timer.timeout.connect(self.update_text)
        self.loading_timer.start(500)

        # 播放设置
        self.is_play = False
        self.input_path = None
        self.input_capture = None
        self.output_path = None
        self.output_capture = None
        self.total_frames = None

        self.final_capture = None
        self.is_play_f = False
        self.current_frame_f = 0
        self.total_frames_f = 0

    def open_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self.ui, "Open Video File", "", "Video Files (*.mp4 *.avi *.mov)")
        if file_name == '':
            return

        self.filename = os.path.basename(file_name)
        self.filename_without_extension, _ = os.path.splitext(self.filename)
        if not os.path.exists(config['hand_result_path'] + self.filename_without_extension):
            os.makedirs(config['hand_result_path'] + self.filename_without_extension)
        if not os.path.exists(config['hand_result_img_path'] + self.filename_without_extension):
            os.makedirs(config['hand_result_img_path'] + self.filename_without_extension)
        self.is_play = False
        self.ui.loading_widget.hide()
        self.ui.btn_begin_or_pause.setText('播放')
        self.ui.tabWidget.hide()
        self.current_frame = 0
        self.input_path = file_name
        self.input_capture = cv2.VideoCapture(self.input_path)

        self.total_frames = self.input_capture.get(cv2.CAP_PROP_FRAME_COUNT)

        self.is_load = True
        self.ui.upload_box.hide()
        self.ui.loading_widget.show()

        # TODO:参数
        parameters = {'some': 0}
        self.load_thread = LoadThread(parameters)
        self.load_thread.progress.connect(self.initial_window)
        self.load_thread.start()

    def initial_window(self):
        self.is_load = False
        self.output_path = config['output_video_path'] + self.filename
        self.output_capture = cv2.VideoCapture(self.output_path)
        self.ui.upload_box.hide()
        self.ui.loading_widget.hide()
        self.ui.setGeometry(200, 200, 1080, 720)
        self.ui.tabWidget.show()
        self.update_frame(initial=True)

    def update_frame(self, initial=False):
        # 更新输入视频
        if self.input_capture is not None:
            if self.is_play or initial:
                retval, frame = self.input_capture.read()
                if retval:
                    # 更新进度条和帧率
                    current_progress = round(1000 * self.current_frame / self.total_frames)
                    self.ui.video_progress.setValue(current_progress)
                    self.current_frame += 1

                    height, width = self.ui.input_video.height(), self.ui.input_video.width()
                    h, w, ch = frame.shape
                    scale = min(height / h, width / w)
                    new_h, new_w = round(scale * h), round(scale * w)

                    affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                                           np.float32([
                                                               [width / 2, height / 2],
                                                               [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                               [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                                           ]))

                    frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    self.ui.input_video.setPixmap(QPixmap.fromImage(q_img))

                else:
                    self.input_capture.release()

        # 更新输出视频
        if self.output_capture is not None:
            if self.is_play or initial:
                retval, frame = self.output_capture.read()
                if retval:
                    height, width = self.ui.output_video.height(), self.ui.output_video.width()
                    h, w, ch = frame.shape
                    scale = min(height / h, width / w)
                    new_h, new_w = round(scale * h), round(scale * w)

                    affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                                           np.float32([
                                                               [width / 2, height / 2],
                                                               [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                               [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                                           ]))

                    frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    self.ui.output_video.setPixmap(QPixmap.fromImage(q_img))
                else:
                    self.output_capture.release()

    def update_text(self):
        if self.is_load:
            self.dots = (self.dots + 1) % 4  # 控制点的数量
            loading_text = '加载中' + '.' * self.dots
            self.ui.loading_label.setText(loading_text)

    def control_video(self):
        self.is_play = not self.is_play
        self.ui.btn_begin_or_pause.setText('暂停' if self.is_play else '播放')

    def control_video_f(self):
        self.is_play_f = not self.is_play_f
        self.ui.btn_begin_or_pause_3.setText('暂停' if self.is_play_f else '播放')

    def slider_pressed(self):
        self.is_play = False
        self.ui.btn_begin_or_pause.setText('暂停' if self.is_play else '播放')

    def jump_by_ratio_3(self):
        obj_progress_f = self.ui.video_progress_3.value()
        obj_frame_f = round(self.total_frames_f * obj_progress_f / 1000)
        self.current_frame_f = obj_frame_f
        self.final_capture.set(cv2.CAP_PROP_POS_FRAMES, obj_frame_f)
        self.is_play_f = True
        self.ui.btn_begin_or_pause_3.setText('暂停' if self.is_play_f else '播放')

    def slider_pressed_3(self):
        self.is_play_f = False
        self.ui.btn_begin_or_pause_3.setText('暂停' if self.is_play_f else '播放')

    def jump_by_ratio(self):
        obj_progress = self.ui.video_progress.value()
        obj_frame = round(self.total_frames * obj_progress / 1000)
        self.current_frame = obj_frame
        self.input_capture.set(cv2.CAP_PROP_POS_FRAMES, obj_frame)
        self.output_capture.set(cv2.CAP_PROP_POS_FRAMES, obj_frame)
        self.is_play = True
        self.ui.btn_begin_or_pause.setText('暂停' if self.is_play else '播放')

    def video_replay(self):
        self.input_capture = cv2.VideoCapture(self.input_path)
        self.output_capture = cv2.VideoCapture(self.output_path)
        self.current_frame = 0
        self.is_play = True
        self.ui.btn_begin_or_pause.setText('暂停' if self.is_play else '播放')

    def video_replay_f(self):
        self.final_capture = cv2.VideoCapture(config['final_video_path'] + self.filename)
        self.current_frame_f = 0
        self.is_play_f = True
        self.ui.btn_begin_or_pause_3.setText('暂停' if self.is_play_f else '播放')

    def save_file(self):
        pass

    def open_FPS_dialog(self):
        FPS, confirm = QInputDialog.getInt(self.ui, '设置帧率', '输入1-60之间的整数:', minValue=1, maxValue=60)
        if confirm:
            self.timer.start(1000 / FPS)
            self.ui.FPS_label.setText('FPS : ' + str(FPS) + '    ')

    def display_FPS(self):
        if self.ui.FPS_label.isHidden():
            self.ui.FPS_label.show()
            self.ui.FPS_label_3.show()
        else:
            self.ui.FPS_label.hide()
            self.ui.FPS_label_3.hide()

    def get_sotred_result(self):
        try:
            self.sorted_results = os.listdir(config['output_img_path'] + self.filename_without_extension)
            self.origin_img = os.listdir(config['input_img_path'] + self.filename_without_extension)
            self.current_page = 0
            self.ui.sum_label.setText(f'图片总数 : {len(self.sorted_results)}')
            self.ui.current_index.setValue(self.current_page + 1)
        except:
            QMessageBox.warning(self.ui, '警告', '结果不存在')
            self.sorted_results = None
            self.origin_img = None
            return

        frame = cv2.imread(
            config['output_img_path'] + '/' + self.filename_without_extension + '/' + self.sorted_results[0])

        height, width = self.ui.algorithm_result.height(), self.ui.algorithm_result.width()
        h, w, ch = frame.shape
        scale = min(height / h, width / w)
        new_h, new_w = round(scale * h), round(scale * w)

        affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                               np.float32([
                                                   [width / 2, height / 2],
                                                   [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                   [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                               ]))

        frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.ui.algorithm_result.setPixmap(QPixmap.fromImage(q_img))

    def prev_result(self):
        if self.current_page <= 0:
            QMessageBox.warning(self.ui, '警告', '已达最小索引')
        else:
            self.current_page -= 1
            self.ui.current_index.setValue(self.current_page + 1)

    def next_result(self):
        if self.current_page >= len(self.sorted_results) - 1:
            QMessageBox.warning(self.ui, '警告', '已达最大索引')
        else:
            self.current_page += 1
            self.ui.current_index.setValue(self.current_page + 1)

    def change_result(self):
        if self.sorted_results is not None:
            frame = cv2.imread(
                config['output_img_path'] + '/' + self.filename_without_extension + '/' + self.sorted_results[
                    self.current_page])

            height, width = self.ui.algorithm_result.height(), self.ui.algorithm_result.width()
            if not self.is_fixed:
                self.ui.algorithm_result.setFixedSize(height, width)
                self.ui.hand_result.setFixedSize(height, width)
                self.is_fixed = True
            h, w, ch = frame.shape
            scale = min(height / h, width / w)
            new_h, new_w = round(scale * h), round(scale * w)

            affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                                   np.float32([
                                                       [width / 2, height / 2],
                                                       [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                       [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                                   ]))

            frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.ui.algorithm_result.setPixmap(QPixmap.fromImage(q_img))
            # self.ui.algorithm_result.setFixedSize(height, width)

    def hand_mark(self):
        input_path = config['input_img_path'] + self.filename_without_extension + '/' + self.origin_img[
            self.current_page]
        os.path.splitext(self.origin_img[self.current_page])
        img_name, _ = os.path.splitext(self.origin_img[self.current_page])
        output_path = config['hand_result_path'] + self.filename_without_extension + '/' + img_name + '.json'
        img_path = config['hand_result_img_path'] + self.filename_without_extension + '/' + img_name + '.png'
        self.hand_thread = HandThread(input_path, output_path, img_path,
                                      config['hand_result_path'] + self.filename_without_extension)
        self.hand_thread.success.connect(self.display_hand_result)
        self.hand_thread.start()

    def display_hand_result(self):
        path = config['hand_result_img_path'] + self.filename_without_extension + '/' + self.origin_img[
            self.current_page]
        frame = cv2.imread(path)

        height, width = self.ui.hand_result.height(), self.ui.hand_result.width()
        h, w, ch = frame.shape
        scale = min(height / h, width / w)
        new_h, new_w = round(scale * h), round(scale * w)

        affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                               np.float32([
                                                   [width / 2, height / 2],
                                                   [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                   [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                               ]))

        frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.ui.hand_result.setPixmap(QPixmap.fromImage(q_img))

    def update_frame_f(self, initial=False):
        # 更新输入视频
        if self.final_capture is not None:
            if self.is_play_f or initial:
                retval, frame = self.final_capture.read()
                if retval:
                    # 更新进度条和帧率
                    current_progress_f = round(1000 * self.current_frame_f / self.total_frames_f)
                    self.ui.video_progress_3.setValue(current_progress_f)
                    self.current_frame_f += 1

                    height, width = self.ui.final_video.height(), self.ui.final_video.width()
                    h, w, ch = frame.shape
                    scale = min(height / h, width / w)
                    new_h, new_w = round(scale * h), round(scale * w)

                    affine_matrix = cv2.getAffineTransform(np.float32([[w / 2, h / 2], [0, 0], [0, h]]),
                                                           np.float32([
                                                               [width / 2, height / 2],
                                                               [width / 2 - new_w / 2, height / 2 - new_h / 2],
                                                               [width / 2 - new_w / 2, height / 2 + new_h / 2]
                                                           ]))

                    frame = cv2.warpAffine(frame, affine_matrix, (width, height), borderMode=cv2.BORDER_CONSTANT)

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    self.ui.final_video.setPixmap(QPixmap.fromImage(q_img))

                else:
                    self.final_capture.release()

    def integrate_video(self):
        enhanced_img_path = os.path.join(config['output_img_path'], self.filename_without_extension)
        hand_marked_img_path = os.path.join(config['hand_result_img_path'], self.filename_without_extension)
        output_path = os.path.join(config['final_video_path'], self.filename)

        self.integration_thread = IntegrationThread(enhanced_img_path, hand_marked_img_path, output_path)
        self.integration_thread.success.connect(self.play_final_video)
        self.integration_thread.start()

    def play_final_video(self):
        QMessageBox.information(self.ui, '生成成功', '生成成功')
        self.is_play_f = False
        self.ui.btn_begin_or_pause_3.setText('播放')
        self.current_frame_f = 0
        self.final_capture = cv2.VideoCapture(config['final_video_path'] + self.filename)
        self.total_frames_f = self.final_capture.get(cv2.CAP_PROP_FRAME_COUNT)
        self.update_frame_f(initial=True)

    def closeEvent(self, event):
        if self.input_capture:
            self.input_capture.release()
        if self.output_capture:
            self.output_capture.release()
        if self.final_capture:
            self.final_capture.release()
        event.accept()


if __name__ == '__main__':
    app = QApplication([])
    main_window = MainWindow()
    main_window.ui.show()
    app.exec()
