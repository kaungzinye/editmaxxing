Pod::Spec.new do |s|
  s.name = 'SourceAudio'
  s.version = '1.0.0'
  s.summary = 'Canonical source audio extraction for endpoint testing'
  s.description = s.summary
  s.author = 'editmaxxing'
  s.homepage = 'https://github.com/kaungzinye/editmaxxing'
  s.license = { :type => 'MIT' }
  s.platforms = { :ios => '16.4' }
  s.source = { :git => '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.swift_version = '5.9'
  s.source_files = '**/*.swift'
end
