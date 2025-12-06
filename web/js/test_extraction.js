// Test script for filename extraction logic

const urls = [
    "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors?download=true",
    "https://hf.co/user/repo/resolve/main/model.ckpt",
    "https://huggingface.co/user/repo/blob/main/folder/file.pt?download=true&other=param",
    "https://civitai.com/models/12345?modelVersionId=67890", // should be ignored
    "https://example.com/file.zip" // should be ignored
];

console.log("Testing URL Filename Extraction:\n");

urls.forEach(url => {
    const urlLower = url.toLowerCase();
    let filename = "";

    if (urlLower.includes('huggingface.co') || urlLower.includes('hf.co')) {
        try {
            const cleanUrl = url.split('?')[0];
            const parts = cleanUrl.split('/');
            filename = parts[parts.length - 1];
        } catch (e) {
            console.error("Error extracting:", e);
        }
    }

    console.log(`URL: ${url}`);
    console.log(`Extracted Filename: "${filename}"`);
    console.log("-----------------------------------");
});
