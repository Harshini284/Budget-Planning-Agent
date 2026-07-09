document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("input[type='number']").forEach(function (input) {
        input.addEventListener("input", function () {
            input.value = input.value.replace(/[^0-9.]/g, "");
        });
    });
});
