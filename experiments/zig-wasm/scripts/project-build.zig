// AI-assisted default project library build; placeholders are JSON-quoted strings.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const module = b.createModule(.{
        .root_source_file = b.path(__ZIG_ROOT__),
        .target = b.standardTargetOptions(.{}),
        .optimize = b.standardOptimizeOption(.{}),
        .pic = true,
    });
    for ([_]std.builtin.LinkMode{ .dynamic, .static }) |linkage| {
        const lib = b.addLibrary(.{
            .name = __LIBRARY_NAME__,
            .linkage = linkage,
            .root_module = module,
        });
        b.installArtifact(lib);
    }
}
