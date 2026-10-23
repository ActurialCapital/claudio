// claudio-audio: Apple's voice-processing I/O unit (the FaceTime echo canceller) as a pipe.
// stdin:  speech to play, 24 kHz mono int16.   stdout: echo-cancelled mic, 24 kHz mono int16.
// One unit does both, so it knows what it is playing and removes it from the mic.
// Raw AudioToolbox rather than AVAudioEngine: the engine's wrapper fails to initialise it on recent macOS.
import AudioToolbox
import Foundation

let RATE = 24000.0
var fmt = AudioStreamBasicDescription(
    mSampleRate: RATE, mFormatID: kAudioFormatLinearPCM,
    mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked,
    mBytesPerPacket: 2, mFramesPerPacket: 1, mBytesPerFrame: 2, mChannelsPerFrame: 1, mBitsPerChannel: 16, mReserved: 0)

/// What stdin gave us and the speaker has not played yet.
final class Ring {
    private var buf = [Int16]()
    private let lock = NSLock()
    func put(_ data: Data) {
        lock.lock(); defer { lock.unlock() }
        data.withUnsafeBytes { raw in buf.append(contentsOf: raw.bindMemory(to: Int16.self)) }
    }
    func clear() {
        lock.lock(); buf.removeAll(); lock.unlock()
    }
    func take(into p: UnsafeMutablePointer<Int16>, count: Int) {
        lock.lock(); defer { lock.unlock() }
        let n = min(count, buf.count)
        for i in 0..<n { p[i] = buf[i] }
        for i in n..<count { p[i] = 0 }
        buf.removeFirst(n)
    }
}
let ring = Ring()
var unit: AudioUnit!
let writer = DispatchQueue(label: "mic-out")
let stdout = FileHandle.standardOutput

/// The speaker asks for samples.
let render: AURenderCallback = { _, _, _, _, frames, ioData in
    guard let ioData = ioData else { return noErr }
    for b in UnsafeMutableAudioBufferListPointer(ioData) {
        ring.take(into: b.mData!.assumingMemoryBound(to: Int16.self), count: Int(b.mDataByteSize) / 2)
    }
    return noErr
}

/// The mic has samples: pull them through the unit (echo removed) and ship them.
let capture: AURenderCallback = { _, flags, ts, bus, frames, _ in
    let bytes = Int(frames) * 2
    var abl = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(bytes), mData: malloc(bytes)))
    let st = AudioUnitRender(unit, flags, ts, 1, frames, &abl)
    if st == noErr {
        let data = Data(bytes: abl.mBuffers.mData!, count: Int(abl.mBuffers.mDataByteSize))
        writer.async { stdout.write(data) }
    }
    free(abl.mBuffers.mData)
    return st
}

func check(_ st: OSStatus, _ what: String) {
    if st != noErr { FileHandle.standardError.write("\(what): \(st)\n".data(using: .utf8)!); exit(2) }
}

var desc = AudioComponentDescription(componentType: kAudioUnitType_Output, componentSubType: kAudioUnitSubType_VoiceProcessingIO,
                                     componentManufacturer: kAudioUnitManufacturer_Apple, componentFlags: 0, componentFlagsMask: 0)
guard let comp = AudioComponentFindNext(nil, &desc) else { FileHandle.standardError.write("no voice-processing unit\n".data(using: .utf8)!); exit(2) }
check(AudioComponentInstanceNew(comp, &unit), "new")
var one: UInt32 = 1
check(AudioUnitSetProperty(unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1, &one, 4), "enable mic")
check(AudioUnitSetProperty(unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Output, 0, &one, 4), "enable speaker")
let fmtSize = UInt32(MemoryLayout.size(ofValue: fmt))
check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &fmt, fmtSize), "mic format")
check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &fmt, fmtSize), "speaker format")
var cb = AURenderCallbackStruct(inputProc: render, inputProcRefCon: nil)
check(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &cb, UInt32(MemoryLayout.size(ofValue: cb))), "render callback")
var icb = AURenderCallbackStruct(inputProc: capture, inputProcRefCon: nil)
check(AudioUnitSetProperty(unit, kAudioOutputUnitProperty_SetInputCallback, kAudioUnitScope_Global, 0, &icb, UInt32(MemoryLayout.size(ofValue: icb))), "input callback")
check(AudioUnitInitialize(unit), "initialize")
check(AudioOutputUnitStart(unit), "start")

// SIGUSR1: drop what is queued (a barge-in).
signal(SIGUSR1, SIG_IGN)
let cutSignal = DispatchSource.makeSignalSource(signal: SIGUSR1, queue: .main)
cutSignal.setEventHandler { ring.clear() }
cutSignal.resume()

// stdin → ring. EOF ends the helper.
DispatchQueue.global(qos: .userInteractive).async {
    let stdin = FileHandle.standardInput
    while true {
        let data = stdin.readData(ofLength: 960)
        if data.isEmpty { AudioOutputUnitStop(unit); exit(0) }
        ring.put(data)
    }
}
RunLoop.main.run()
