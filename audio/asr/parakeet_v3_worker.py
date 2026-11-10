"""Private stdin/stdout worker for NVIDIA NeMo-Speech.cpp v0.3.0 C ABI.

Executed by filename; imports neither Hermes nor the plugin. Never opens devices.
"""
import ctypes as C
import json
import struct
import sys


class Backend(C.Structure):
    _fields_ = [("size", C.c_size_t), ("gpu", C.c_int32)]


class Model(C.Structure):
    _fields_ = [("size", C.c_size_t), ("path", C.c_char_p), ("name", C.c_char_p)]


class Config(C.Structure):
    _fields_ = [("size", C.c_size_t), ("backend", C.POINTER(Backend)),
                ("model", C.POINTER(Model))]


class Options(C.Structure):
    # The ABI explicitly permits a smaller struct with omitted tail defaults.
    _fields_ = [("size", C.c_size_t), ("request_id", C.c_char_p),
                ("language_code", C.c_char_p), ("interim_results", C.c_bool),
                ("enable_word_time_offsets", C.c_bool)]


def main(library, model_path):
    lib = C.CDLL(library)

    def bind(name, result, *args):
        fn = getattr(lib, "nemo_speech_asr_" + name)
        fn.restype, fn.argtypes = result, list(args)
        return fn

    ptr = C.c_void_p
    create = bind("create", C.c_int, C.POINTER(Config), C.POINTER(ptr))
    destroy = bind("destroy", None, ptr)
    recognize = bind("recognize_f32", C.c_int, ptr, C.POINTER(Options),
                     C.POINTER(C.c_float), C.c_size_t, C.c_int32, C.POINTER(ptr))
    free = bind("result_destroy", None, ptr)
    text = bind("result_transcript", C.c_char_p, ptr, C.c_size_t)
    count = bind("result_word_count", C.c_size_t, ptr, C.c_size_t)
    word = bind("result_word_text", C.c_char_p, ptr, C.c_size_t, C.c_size_t)
    start = bind("result_word_start_time", C.c_int32, ptr, C.c_size_t, C.c_size_t)
    end = bind("result_word_end_time", C.c_int32, ptr, C.c_size_t, C.c_size_t)
    error = bind("last_error", C.c_char_p)
    backend = Backend(C.sizeof(Backend), 0)
    model = Model(C.sizeof(Model), model_path.encode(), None)
    config = Config(C.sizeof(Config), C.pointer(backend), C.pointer(model))
    options = Options(C.sizeof(Options), None, None, False, True)
    handle = ptr()

    def check(status):
        if status:
            raise RuntimeError((error() or b"Native recognition failed").decode("utf-8", "replace"))

    def transcribe(samples, rate):
        result = ptr()
        check(recognize(handle, C.byref(options), samples, len(samples), rate, C.byref(result)))
        if not result:
            raise RuntimeError("Native recognition returned no result")
        try:
            return {"text": (text(result, 0) or b"").decode(), "words": [
                {"word": word(result, 0, i).decode(), "start": start(result, 0, i) / 1000,
                 "end": end(result, 0, i) / 1000} for i in range(count(result, 0))]}
        finally:
            free(result)

    check(create(C.byref(config), C.byref(handle)))
    try:
        transcribe((C.c_float * 16000)(), 16000)
        print(json.dumps({"ready": True}), flush=True)
        while True:
            header = sys.stdin.buffer.read(8)
            if not header:
                break
            if len(header) != 8:
                raise ValueError("Incomplete audio header")
            n, rate = struct.unpack("<II", header)
            if not 8000 <= rate <= 96000 or n > rate * 30:
                raise ValueError("Invalid audio dimensions")
            data = sys.stdin.buffer.read(n * 4)
            if len(data) != n * 4:
                raise ValueError("Incomplete audio samples")
            samples = (C.c_float * n).from_buffer_copy(data)
            print(json.dumps(transcribe(samples, rate)), flush=True)
    finally:
        destroy(handle)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)
