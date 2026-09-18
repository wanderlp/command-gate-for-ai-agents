class Cgate < Formula
  desc "Middleware/CLI between AI agents and servers — IA proposes, human approves."
  homepage "https://github.com/wanderlp/command-gate-for-ai-agents"
  url "https://github.com/wanderlp/command-gate-for-ai-agents/releases/download/v0.1.5/cgate-macos-arm64"
  version "0.1.5"
  sha256 "PLACEHOLDER_UPDATE_AFTER_RELEASE"
  license "MIT"

  # arm64 (Apple Silicon) only -- release.yml's macOS runner only builds
  # cgate-macos-arm64. Add an on_intel block back once an x86_64 asset exists;
  # shipping one that 404s is worse than not offering Intel support at all.

  def install
    bin.install "cgate-macos-arm64" => "cgate"
  end

  test do
    assert_match "cgate #{version}", shell_output("#{bin}/cgate --version")
  end
end
