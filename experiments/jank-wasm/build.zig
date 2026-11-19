const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const module = b.createModule(.{
        .root_source_file = b.path("native.zig"),
        .target = target,
        .optimize = optimize,
        .pic = true,
    });
    for ([_]std.builtin.LinkMode{ .dynamic, .static }) |linkage| {
        const lib = b.addLibrary(.{
            .name = "spike",
            .linkage = linkage,
            .root_module = module,
        });
        b.installArtifact(lib);
    }
    const tests = b.addTest(.{ .root_module = module });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run Zig unit tests").dependOn(&run_tests.step);
}
