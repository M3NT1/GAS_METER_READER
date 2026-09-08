import Foundation
import Vision
import ImageIO
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
let handler = VNImageRequestHandler(url: url, options: [:])
do {
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let encoded = try JSONSerialization.data(withJSONObject: lines)
    print(String(data: encoded, encoding: .utf8)!)
} catch {
    fputs("A helyi kepfelismeres sikertelen: \(error)\n", stderr)
    exit(1)
}
