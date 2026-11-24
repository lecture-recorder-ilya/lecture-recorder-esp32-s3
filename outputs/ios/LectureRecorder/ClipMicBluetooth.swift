import CoreBluetooth
import Foundation

struct ClipMicChoice: Identifiable {
    let id: UUID
    let name: String
    var label: String { "\(name) · \(id.uuidString.suffix(4))" }
}

final class ClipMicBluetooth: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private enum Stage { case waiting, scanning, connecting, status, subscribing, starting, streaming, finished }
    private static let service = CBUUID(string: "b8a10001-51e9-4a0b-8e27-047c45f78210")
    private static let controlID = CBUUID(string: "b8a10005-51e9-4a0b-8e27-047c45f78210")
    private static let audioID = CBUUID(string: "b8a10003-51e9-4a0b-8e27-047c45f78210")

    private let known: UUID?
    private var manager: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var found: [UUID: CBPeripheral] = [:]
    private var control: CBCharacteristic?
    private var audio: CBCharacteristic?
    private var timer: Timer?
    private var deadline = 0.0
    private var stage = Stage.waiting
    private var early: [(Data, TimeInterval)] = []
    private var earlyBytes = 0

    var onChoices: ([ClipMicChoice]) -> Void = { _ in }
    var onPaired: (UUID) -> Void = { _ in }
    var onPacket: (Data, TimeInterval) throws -> Void = { _, _ in }
    var onEnd: (String?) -> Void = { _ in }

    init(known: UUID?) { self.known = known }

    func begin() {
        guard stage == .waiting, manager == nil else { return }
        deadline = ProcessInfo.processInfo.systemUptime + (known == nil ? 60 : 3)
        let tick = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in self?.checkTimeout() }
        timer = tick
        RunLoop.main.add(tick, forMode: .common)
        manager = CBCentralManager(delegate: self, queue: .main,
                                   options: [CBCentralManagerOptionShowPowerAlertKey: false])
    }

    private func checkTimeout() {
        guard stage != .finished, ProcessInfo.processInfo.systemUptime >= deadline else { return }
        finish(stage == .streaming ? "ClipMic перестал передавать звук" :
               (known == nil ? "Время сопряжения истекло. Повтори поиск ClipMic" : "ClipMic не ответил"))
    }

    func choose(_ id: UUID) {
        guard known == nil, stage == .scanning, let device = found[id] else { return }
        deadline = ProcessInfo.processInfo.systemUptime + 45
        connect(device)
    }

    func finish(_ reason: String? = nil) {
        guard stage != .finished else { return }
        let shouldStop = stage == .starting || stage == .streaming
        stage = .finished
        timer?.invalidate()
        timer = nil
        if manager?.isScanning == true { manager?.stopScan() }
        if let device = peripheral {
            if shouldStop, device.state == .connected, let control {
                device.writeValue(Data("STOP".utf8), for: control, type: .withResponse)
            }
            device.delegate = nil
            manager?.cancelPeripheralConnection(device)
        }
        manager?.delegate = nil
        early.removeAll()
        onEnd(reason)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard stage != .finished else { return }
        switch central.state {
        case .poweredOn:
            guard stage == .waiting else { return }
            if let known, let device = central.retrievePeripherals(withIdentifiers: [known]).first {
                connect(device)
            } else {
                stage = .scanning
                central.scanForPeripherals(withServices: [Self.service])
            }
        case .unknown, .resetting:
            if stage == .streaming { finish("Bluetooth прервал запись ClipMic") }
        case .unauthorized: finish("Открой настройки приложения «Коса» и разреши доступ к Bluetooth")
        case .poweredOff: finish("Bluetooth выключен")
        default: finish("Bluetooth для ClipMic недоступен")
        }
    }

    private func connect(_ device: CBPeripheral) {
        stage = .connecting
        if manager?.isScanning == true { manager?.stopScan() }
        peripheral = device
        device.delegate = self
        manager?.connect(device)
    }

    func centralManager(_ central: CBCentralManager, didDiscover device: CBPeripheral,
                        advertisementData: [String: Any], rssi: NSNumber) {
        guard stage == .scanning else { return }
        if let known {
            if device.identifier == known { connect(device) }
        } else {
            found[device.identifier] = device
            onChoices(found.values.map { ClipMicChoice(id: $0.identifier, name: $0.name ?? "ClipMic") }
                .sorted { $0.label < $1.label })
        }
    }

    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) {
        guard stage == .connecting, device === peripheral else { return }
        device.discoverServices([Self.service])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect device: CBPeripheral, error: Error?) {
        finish("Не удалось подключиться к ClipMic")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral device: CBPeripheral, error: Error?) {
        finish("Связь с ClipMic прервалась")
    }

    func peripheral(_ device: CBPeripheral, didDiscoverServices error: Error?) {
        guard stage == .connecting else { return }
        guard error == nil, let service = device.services?.first(where: { $0.uuid == Self.service }) else {
            finish("На устройстве нет сервиса ClipMic")
            return
        }
        device.discoverCharacteristics([Self.controlID, Self.audioID], for: service)
    }

    func peripheral(_ device: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard stage == .connecting else { return }
        control = service.characteristics?.first { $0.uuid == Self.controlID }
        audio = service.characteristics?.first { $0.uuid == Self.audioID }
        guard error == nil, let control, let audio, control.properties.contains([.write, .read]),
              audio.properties.contains(.notify) else {
            finish("Для записи нужен ClipMic с прошивкой Bluetooth-сопряжения")
            return
        }
        if known == nil {
            stage = .status
            device.writeValue(Data("STATUS".utf8), for: control, type: .withResponse)
        } else {
            stage = .subscribing
            device.setNotifyValue(true, for: audio)
        }
    }

    func peripheral(_ device: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard stage == .subscribing, characteristic.uuid == Self.audioID else { return }
        guard error == nil, characteristic.isNotifying, let control else {
            finish("ClipMic не открыл поток звука")
            return
        }
        stage = .starting
        device.writeValue(Data("START".utf8), for: control, type: .withResponse)
    }

    func peripheral(_ device: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard characteristic.uuid == Self.controlID, stage == .status || stage == .starting else { return }
        guard error == nil else { finish("Подтверди сопряжение с ClipMic и повтори"); return }
        device.readValue(for: characteristic)
    }

    func peripheral(_ device: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard stage != .finished else { return }
        guard error == nil, let data = characteristic.value else { finish("Ошибка чтения ClipMic"); return }
        if characteristic.uuid == Self.controlID {
            let reply = String(decoding: data, as: UTF8.self)
            if stage == .status {
                guard reply == "READY 16000 mic=1" || reply == "READY 16000 mic=0" else {
                    finish("Удержи REC или BOOT на ClipMic, подтверди сопряжение и повтори")
                    return
                }
                onPaired(device.identifier)
                finish()
            } else if stage == .starting {
                guard reply == "READY 16000 PCM16" else { finish("ClipMic не разрешил запись"); return }
                stage = .streaming
                for (packet, arrival) in early where stage == .streaming { deliver(packet, arrival: arrival) }
                early.removeAll()
            }
        } else if characteristic.uuid == Self.audioID {
            if stage == .starting {
                earlyBytes += data.count
                guard earlyBytes <= 65536 else { finish("ClipMic не подтвердил начало записи"); return }
                early.append((data, ProcessInfo.processInfo.systemUptime))
            } else if stage == .streaming { deliver(data, arrival: ProcessInfo.processInfo.systemUptime) }
        }
    }

    private func deliver(_ packet: Data, arrival: TimeInterval) {
        do {
            try onPacket(packet, arrival)
            deadline = ProcessInfo.processInfo.systemUptime + 3
        } catch { finish(error.localizedDescription) }
    }
}
