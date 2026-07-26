-- ============================================================
--  Everyday Neovim config — Python-focused, autocomplete + file tree
--  Location: ~/.config/nvim/init.lua
--  Launch:   nvim   (or nvim somefile.py)
-- ============================================================

-- ── Bootstrap lazy.nvim (plugin manager) ────────────────────
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  vim.fn.system({
    "git", "clone", "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable", lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

-- ── Basic options ────────────────────────────────────────────
vim.g.mapleader = " "
vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.signcolumn = "yes"
vim.opt.termguicolors = true
vim.opt.cursorline = true
vim.opt.expandtab = true
vim.opt.shiftwidth = 4
vim.opt.tabstop = 4
vim.opt.smartindent = true
vim.opt.updatetime = 250
vim.opt.pumheight = 15
vim.opt.scrolloff = 8
vim.opt.wrap = false
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.splitright = true
vim.opt.splitbelow = true
vim.opt.clipboard = "unnamedplus"  -- share clipboard with system
vim.opt.foldmethod = "expr"
vim.opt.foldexpr = "v:lua.vim.lsp.foldexpr()"
vim.opt.foldlevelstart = 99  -- start with all folds open
vim.opt.spelllang = "en_us"
vim.opt.spell = true

-- remove arrowkeys --
vim.keymap.set({"n", "i", "v"}, "<Up>", "<Nop>")
vim.keymap.set({"n", "i", "v"}, "<Down>", "<Nop>")
vim.keymap.set({"n", "i", "v"}, "<Left>", "<Nop>")
vim.keymap.set({"n", "i", "v"}, "<Right>", "<Nop>")


-- Quick escape from insert mode
vim.keymap.set("i", "jk", "<Esc>")
vim.keymap.set("i", "JK", "<Esc>")

-- Quality-of-life keymaps
vim.keymap.set("n", "<leader>w", "<cmd>w<cr>", { desc = "Save file" })
vim.keymap.set("n", "<leader>q", "<cmd>q<cr>", { desc = "Quit" })
vim.keymap.set("n", "<C-h>", "<C-w>h", { desc = "Move to left split" })
vim.keymap.set("n", "<C-l>", "<C-w>l", { desc = "Move to right split" })
vim.keymap.set("n", "<C-j>", "<C-w>j", { desc = "Move to split below" })
vim.keymap.set("n", "<C-k>", "<C-w>k", { desc = "Move to split above" })
vim.keymap.set("n", "<leader>cs", function() require("lint").try_lint() end, { desc = "Run cspell lint" })

-- ── Plugins ──────────────────────────────────────────────────
require("lazy").setup({

  -- Colorscheme
  {
    "catppuccin/nvim",
    name = "catppuccin",
    priority = 1000,
    config = function()
      require("catppuccin").setup({
        flavour = "mocha",
        integrations = {
          cmp = true,
          treesitter = true,
          native_lsp = { enabled = true },
          gitsigns = true,
          nvimtree = true,
          which_key = true,
        },
      custom_highlights = function(colors)
        return {
          Normal = { bg = "#000000" },
          NormalFloat = { bg = "#000000" },
          NvimTreeNormal = { bg = "#000000" },
          TelescopeNormal = { bg = "#000000" },
        }
      end,
      })
      vim.cmd.colorscheme("catppuccin")
    end,
  },

  -- Treesitter — real syntax highlighting/parsing
  -- NOTE: on Neovim 0.12+ you must use the default/main branch (master is frozen
  -- and only supports 0.10/0.11). The setup API changed in the rewrite.
  {
    "nvim-treesitter/nvim-treesitter",
    lazy = false,
    build = ":TSUpdate",
    config = function()
      require("nvim-treesitter").setup({
        -- parsers install into stdpath('data')/site by default
      })

      -- Install parsers asynchronously (no-op if already present)
      -- markdown_inline is required by markdown injections / render-markdown.nvim
      require("nvim-treesitter").install({
        "python", "lua", "vim", "vimdoc",
        "json", "yaml", "toml",
        "markdown", "markdown_inline",
        "bash",
      })

      -- Highlighting is no longer a nvim-treesitter "module"; start it per buffer.
      vim.api.nvim_create_autocmd("FileType", {
        callback = function(ev)
          -- pcall so missing parsers don't hard-error on every buffer
          pcall(vim.treesitter.start, ev.buf)
        end,
      })

      -- Optional: treesitter-based indentation (experimental on main)
      vim.api.nvim_create_autocmd("FileType", {
        pattern = {
          "python", "lua", "vim", "json", "yaml", "toml", "markdown", "bash",
        },
        callback = function()
          vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
        end,
      })
    end,
  },

{
  "mfussenegger/nvim-lint",
  event = { "BufReadPre", "BufWritePost" },
  config = function()
    require("lint").linters_by_ft = {
      ["*"] = { "cspell" },
    }

    vim.api.nvim_create_autocmd({ "BufWritePost", "InsertLeave" }, {
      callback = function()
        require("lint").try_lint()
      end,
    })
  end,
},

  -- Mason — installs LSP servers/formatters/linters for you
  { "williamboman/mason.nvim", config = true },
  {
    "williamboman/mason-lspconfig.nvim",
    dependencies = { "mason.nvim", "neovim/nvim-lspconfig" },
    opts = {
      ensure_installed = { "basedpyright", "ruff", "lua_ls" },
    },
  },

  -- LSP config
  { "neovim/nvim-lspconfig" },

  -- Completion engine
  {
    "hrsh7th/nvim-cmp",
    dependencies = {
      "hrsh7th/cmp-nvim-lsp",
      "hrsh7th/cmp-buffer",
      "hrsh7th/cmp-path",
      "L3MON4D3/LuaSnip",
      "saadparwaiz1/cmp_luasnip",
    },
    config = function()
      local cmp = require("cmp")
      local luasnip = require("luasnip")
      cmp.setup({
        snippet = {
          expand = function(args)
            luasnip.lsp_expand(args.body)
          end,
        },
        mapping = cmp.mapping.preset.insert({
          ["<C-Space>"] = cmp.mapping.complete(),
          ["<CR>"] = cmp.mapping.confirm({ select = true }),
          ["<Tab>"] = cmp.mapping(function(fallback)
            if cmp.visible() then
              cmp.select_next_item()
            elseif luasnip.expand_or_jumpable() then
              luasnip.expand_or_jump()
            else
              fallback()
            end
          end, { "i", "s" }),
          ["<S-Tab>"] = cmp.mapping(function(fallback)
            if cmp.visible() then
              cmp.select_prev_item()
            elseif luasnip.jumpable(-1) then
              luasnip.jump(-1)
            else
              fallback()
            end
          end, { "i", "s" }),
          ["<C-d>"] = cmp.mapping.scroll_docs(4),
          ["<C-u>"] = cmp.mapping.scroll_docs(-4),
        }),
        sources = cmp.config.sources({
          { name = "nvim_lsp" },
          { name = "luasnip" },
        }, {
          { name = "buffer" },
          { name = "path" },
        }),
        window = {
          completion = cmp.config.window.bordered(),
          documentation = cmp.config.window.bordered(),
        },
      })
    end,
  },

  -- File explorer (sidebar tree)
  {
    "nvim-tree/nvim-tree.lua",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
      { "<leader>e", "<cmd>NvimTreeToggle<cr>", desc = "Toggle file tree" },
    },
    config = function()
      require("nvim-tree").setup({
        view = { width = 32 },
        renderer = {
          group_empty = true,
          highlight_git = true,
          icons = {
            show = { git = true },
          },
        },
        git = {
          enable = true,
          ignore = false,  -- still show .gitignore'd files, but marked
        },
        filters = { dotfiles = false },
      })
    end,
  },

  -- Status line
  {
    "nvim-lualine/lualine.nvim",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    config = function()
      require("lualine").setup({
        sections = {
          lualine_c = {
            "filename",
            { "diagnostics", sources = { "nvim_lsp" } },
          },
          lualine_x = {
            function()
              local clients = vim.lsp.get_clients({ bufnr = 0 })
              if #clients > 0 then
                return "  " .. clients[1].name
              end
              return ""
            end,
            "filetype",
          },
        },
      })
    end,
  },

  -- Trouble — pretty diagnostics list
  {
    "folke/trouble.nvim",
    cmd = "Trouble",
    keys = {
      { "<leader>xx", "<cmd>Trouble diagnostics toggle<cr>", desc = "Diagnostics" },
      { "<leader>xs", "<cmd>Trouble symbols toggle<cr>", desc = "Symbols" },
    },
    config = true,
  },

  -- Fidget — LSP progress spinner (bottom-right "loading..." indicator)
  {
    "j-hui/fidget.nvim",
    config = function()
      require("fidget").setup({})
    end,
  },

  -- Indent guides
  {
    "lukas-reineke/indent-blankline.nvim",
    main = "ibl",
    config = function()
      require("ibl").setup({})
    end,
  },

-- Markdown preview (inline rendering, no external binary needed)
{
  "MeanderingProgrammer/render-markdown.nvim",
  dependencies = { "nvim-treesitter/nvim-treesitter", "nvim-tree/nvim-web-devicons" },
  ft = { "markdown" },
  config = true,
},

  -- Which-key — shows keybinding popup as you type
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    config = function()
      require("which-key").setup({})
    end,
  },

  -- Telescope — fuzzy finder for files, text, symbols
  {
    "nvim-telescope/telescope.nvim",
    dependencies = { "nvim-lua/plenary.nvim" },
    keys = {
      { "<leader>ff", "<cmd>Telescope find_files<cr>", desc = "Find Files" },
      { "<leader>fg", "<cmd>Telescope live_grep<cr>", desc = "Grep" },
      { "<leader>fb", "<cmd>Telescope buffers<cr>", desc = "Buffers" },
      { "<leader>fs", "<cmd>Telescope lsp_document_symbols<cr>", desc = "Document Symbols" },
      { "<leader>fw", "<cmd>Telescope lsp_workspace_symbols<cr>", desc = "Workspace Symbols" },
      { "<leader>fd", "<cmd>Telescope diagnostics<cr>", desc = "Diagnostics" },
    },
    config = true,
  },

  -- Git signs in the gutter (added/changed/removed lines)
  {
    "lewis6991/gitsigns.nvim",
    config = function()
      require("gitsigns").setup({})
    end,
  },

  -- Auto-close brackets, quotes, etc.
  {
    "windwp/nvim-autopairs",
    event = "InsertEnter",
    config = true,
  },

  -- Comment toggling (gcc / gc)
  {
    "numToStr/Comment.nvim",
    config = true,
  },

  -- Quick-access floating terminal
  {
    "akinsho/toggleterm.nvim",
    version = "*",
    keys = {
      { "<C-t>", "<cmd>ToggleTerm<cr>", desc = "Toggle terminal", mode = { "n", "t" } },
    },
    opts = {
      direction = "float",  -- or "horizontal" / "vertical"
      size = 15,
    },
  },

}, {
  install = { colorscheme = { "catppuccin" } },
})

-- ── LSP servers ──────────────────────────────────────────────
local capabilities = require("cmp_nvim_lsp").default_capabilities()

-- Python: type checking, hover, go-to-def, autocomplete
vim.lsp.config["basedpyright"] = {
  cmd = { "basedpyright-langserver", "--stdio" },
  filetypes = { "python" },
  root_markers = { "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".git" },
  capabilities = capabilities,
}
vim.lsp.enable("basedpyright")

-- Python: fast linting + formatting
vim.lsp.config["ruff"] = {
  cmd = { "ruff", "server" },
  filetypes = { "python" },
  root_markers = { "pyproject.toml", "ruff.toml", ".git" },
  capabilities = capabilities,
}
vim.lsp.enable("ruff")

-- Lua: for editing this config itself
vim.lsp.config["lua_ls"] = {
  cmd = { "lua-language-server" },
  filetypes = { "lua" },
  root_markers = { ".luarc.json", ".git" },
  capabilities = capabilities,
  settings = {
    Lua = {
      diagnostics = { globals = { "vim" } },
    },
  },
}
vim.lsp.enable("lua_ls")

-- ── LSP keymaps (on attach to a buffer) ──────────────────────
vim.api.nvim_create_autocmd("LspAttach", {
  callback = function(ev)
    local opts = { buffer = ev.buf }
    vim.keymap.set("n", "gd", vim.lsp.buf.definition, opts)
    vim.keymap.set("n", "gr", vim.lsp.buf.references, opts)
    vim.keymap.set("n", "K", vim.lsp.buf.hover, opts)
    vim.keymap.set("n", "<leader>rn", vim.lsp.buf.rename, opts)
    vim.keymap.set("n", "<leader>ca", vim.lsp.buf.code_action, opts)
    vim.keymap.set("n", "<leader>f", function() vim.lsp.buf.format({ async = true }) end, opts)
    vim.keymap.set("n", "[d", vim.diagnostic.goto_prev, opts)
    vim.keymap.set("n", "]d", vim.diagnostic.goto_next, opts)
    vim.keymap.set("n", "<leader>e2", vim.diagnostic.open_float, opts)
    vim.keymap.set("i", "<C-s>", vim.lsp.buf.signature_help, opts)
    vim.lsp.inlay_hint.enable(true, { bufnr = ev.buf })

    -- Toggle inlay hints on/off
    vim.keymap.set("n", "<leader>ih", function()
      vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = ev.buf }), { bufnr = ev.buf })
    end, vim.tbl_extend("force", opts, { desc = "Toggle inlay hints" }))
  end,
})

-- Format Python on save using ruff
vim.api.nvim_create_autocmd("BufWritePre", {
  pattern = "*.py",
  callback = function()
    vim.lsp.buf.format({ async = false })
  end,
})

-- ── Diagnostics appearance ───────────────────────────────────
vim.diagnostic.config({
  virtual_text = false,
  signs = true,
  underline = true,
  update_in_insert = false,
  float = { border = "rounded", source = true },
})

-- Open file tree automatically when starting Neovim on a directory
vim.api.nvim_create_autocmd("VimEnter", {
  callback = function(data)
    if vim.fn.isdirectory(data.file) == 1 then
      vim.cmd.cd(data.file)
      require("nvim-tree.api").tree.open()
    end
  end,
})
